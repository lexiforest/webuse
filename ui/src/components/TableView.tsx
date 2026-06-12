import { For, createMemo, createSignal, type JSX } from "solid-js";

import Pagination from "~/components/Pagination";

type TableViewProps<T> = {
  items: T[];
  columns: JSX.Element[];
  pageSize?: number;
  itemLabel?: string;
  loading?: boolean;
  loadingText?: string;
  emptyText?: string;
  renderRow: (item: T) => JSX.Element;
};

export default function TableView<T>(props: TableViewProps<T>) {
  const [page, setPage] = createSignal(1);
  const pageSize = () => props.pageSize ?? 10;
  const totalPages = () => Math.max(1, Math.ceil(props.items.length / pageSize()));
  const currentPage = () => Math.min(page(), totalPages());
  const pageItems = createMemo(() => {
    const start = (currentPage() - 1) * pageSize();
    return props.items.slice(start, start + pageSize());
  });

  return (
    <>
      <div class="overflow-x-auto">
        <table class="data-table">
          <thead>
            <tr>
              <For each={props.columns}>{column => <th>{column}</th>}</For>
            </tr>
          </thead>
          <tbody>
            <For
              each={pageItems()}
              fallback={
                <tr>
                  <td class="py-10 text-center text-gray-500" colspan={props.columns.length}>
                    {props.loading
                      ? props.loadingText ?? "Loading..."
                      : props.emptyText ?? "No rows yet."}
                  </td>
                </tr>
              }
            >
              {item => props.renderRow(item)}
            </For>
          </tbody>
        </table>
      </div>
      <Pagination
        page={currentPage()}
        pageSize={pageSize()}
        totalItems={props.items.length}
        itemLabel={props.itemLabel}
        onPageChange={setPage}
      />
    </>
  );
}
