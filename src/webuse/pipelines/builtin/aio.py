"""Async destinations using aiofile, aiosqlite, and curl_cffi."""

import asyncio
import csv
import hashlib
import io
from datetime import datetime, timezone
from weakref import WeakValueDictionary

import aiosqlite
from aiofile import async_open
from curl_cffi import AsyncSession
from pydantic import BaseModel

from ...exceptions import PipelineError, PipelineStateError
from ..base import AsyncItemPipeline
from ..utils import ensure_pipeline_item, item_to_dict, item_to_json
from .assets import AssetDownloadPipeline, _asset_path, _content, _urls_from_item
from .csv import CsvPipeline, _csv_value
from .jsonl import JsonlPipeline
from .sqlite import SQLitePipeline
from .webhook import WebhookPipeline, _response_text


class AsyncJsonlPipeline(JsonlPipeline, AsyncItemPipeline):
    async def open_spider(self) -> None:
        self._write_lock = asyncio.Lock()
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._file = await async_open(
            self.path, "a" if self.append else "w", encoding="utf-8"
        )

    async def process_item(self, item: BaseModel) -> BaseModel:
        if self._file is None:
            raise PipelineStateError("AsyncJsonlPipeline is not open")
        line = item_to_json(item) + "\n"
        async with self._write_lock:
            await self._file.write(line)
        return item

    async def close_spider(self) -> None:
        if self._file is not None:
            try:
                await self._file.close()
            finally:
                self._file = None


class AsyncCsvPipeline(CsvPipeline, AsyncItemPipeline):
    async def open_spider(self) -> None:
        self._write_lock = asyncio.Lock()
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._write_header = not self.append or not await asyncio.to_thread(
            lambda: self.path.exists() and self.path.stat().st_size > 0
        )
        self._file = await async_open(
            self.path, "a" if self.append else "w", encoding="utf-8"
        )
        self._writer = None

    async def process_item(self, item: BaseModel) -> BaseModel:
        if self._file is None:
            raise PipelineStateError("AsyncCsvPipeline is not open")
        row = {key: _csv_value(value) for key, value in item_to_dict(item).items()}
        async with self._write_lock:
            buffer = io.StringIO(newline="")
            self.fieldnames = self.fieldnames or list(row)
            writer = csv.DictWriter(buffer, self.fieldnames, extrasaction="ignore")
            if self._write_header:
                writer.writeheader()
            writer.writerow(row)
            await self._file.write(buffer.getvalue())
            self._write_header = False
        return item

    async def close_spider(self) -> None:
        if self._file is not None:
            try:
                await self._file.close()
            finally:
                self._file = None


class AsyncSQLitePipeline(SQLitePipeline, AsyncItemPipeline):
    async def open_spider(self) -> None:
        self._write_lock = asyncio.Lock()
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        try:
            async with self._connection.execute(
                f"""CREATE TABLE IF NOT EXISTS {self.table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            ):
                pass
            await self._connection.commit()
        except BaseException:
            await self.close_spider()
            raise

    async def process_item(self, item: BaseModel) -> BaseModel:
        if self._connection is None:
            raise PipelineStateError("AsyncSQLitePipeline is not open")
        item = ensure_pipeline_item(item)
        async with self._write_lock:
            async with self._connection.execute(
                f"INSERT INTO {self.table} (item_type, data, created_at) VALUES (?, ?, ?)",
                (
                    type(item).__name__,
                    item_to_json(item),
                    datetime.now(timezone.utc).isoformat(),
                ),
            ):
                pass
            await self._connection.commit()
        return item

    async def close_spider(self) -> None:
        if self._connection is not None:
            try:
                await self._connection.close()
            finally:
                self._connection = None


class AsyncWebhookPipeline(WebhookPipeline, AsyncItemPipeline):
    async def open_spider(self) -> None:
        if self._session is None:
            self._session = AsyncSession()
            self._owns_session = True

    async def process_item(self, item: BaseModel) -> BaseModel:
        if self._session is None:
            raise PipelineStateError("AsyncWebhookPipeline is not open")
        kwargs = dict(self.request_kwargs)
        if self.headers is not None:
            kwargs["headers"] = self.headers
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        response = await self._session.request(
            self.method, self.url, json=item_to_dict(item), **kwargs
        )
        status = getattr(response, "status_code", None)
        ok = 200 <= status < 300 if isinstance(status, int) else False
        if self.success_statuses is not None:
            ok = status in self.success_statuses
        if self.fail_on_error and not ok:
            body = _response_text(response)
            raise PipelineError(
                f"AsyncWebhookPipeline {self.method} {self.url} returned HTTP {status}"
                + (f": {body}" if body else "")
            )
        return item

    async def close_spider(self) -> None:
        try:
            if self._session is not None and self._owns_session:
                await self._session.close()
        finally:
            self._session = None


class AsyncAssetDownloadPipeline(AssetDownloadPipeline, AsyncItemPipeline):
    async def open_spider(self) -> None:
        # Only active downloads and their waiters keep these locks alive.
        self._path_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        await asyncio.to_thread(self.directory.mkdir, parents=True, exist_ok=True)
        if self._session is None:
            self._session = AsyncSession()
            self._owns_session = True

    async def _download(self, url: str) -> dict:
        if self._session is None:
            raise PipelineStateError("AsyncAssetDownloadPipeline is not open")
        relative_path = _asset_path(url)
        lock = self._path_locks.setdefault(relative_path, asyncio.Lock())
        async with lock:
            return await self._download_path(url, relative_path)

    async def _download_path(self, url: str, relative_path: str) -> dict:
        path = self.directory / relative_path
        cached = self.skip_existing and await asyncio.to_thread(path.exists)
        if cached:
            async with async_open(path, "rb") as file:
                content = await file.read()
        else:
            response = await self._session.request(
                self.method, url, **self._request_kwargs()
            )
            status = getattr(response, "status_code", None)
            ok = 200 <= status < 300 if isinstance(status, int) else False
            if self.success_statuses is not None:
                ok = status in self.success_statuses
            if not ok:
                if self.fail_on_error:
                    raise PipelineError(
                        f"AsyncAssetDownloadPipeline {self.method} {url} returned HTTP {status}"
                    )
                return dict(url=url, path=None, checksum=None, size=0, status=status)
            content = _content(response)
            async with async_open(path, "wb") as file:
                await file.write(content)
        return dict(
            url=url,
            path=relative_path,
            checksum=hashlib.sha1(content).hexdigest(),
            size=len(content),
            status="cached" if cached else "downloaded",
        )

    async def process_item(self, item: BaseModel) -> BaseModel:
        item = ensure_pipeline_item(item)
        assets = [
            await self._download(url) for url in _urls_from_item(item, self.urls_field)
        ]
        return item.model_copy(update={self.output_field: assets}) if assets else item

    async def close_spider(self) -> None:
        try:
            if self._session is not None and self._owns_session:
                await self._session.close()
        finally:
            self._session = None
