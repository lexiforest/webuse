import Button from "~/components/Button";

type PaginationProps = {
  page: number;
  pageSize: number;
  totalItems: number;
  itemLabel?: string;
  onPageChange: (page: number) => void;
};

export default function Pagination(props: PaginationProps) {
  const totalPages = () => Math.max(1, Math.ceil(props.totalItems / props.pageSize));
  const startItem = () => (props.totalItems === 0 ? 0 : (props.page - 1) * props.pageSize + 1);
  const endItem = () => Math.min(props.totalItems, props.page * props.pageSize);
  const itemLabel = () => props.itemLabel ?? "items";

  return (
    <div class="mt-4 flex flex-col gap-3 border-t border-gray-800 pt-4 text-xs text-gray-400 sm:flex-row sm:items-center sm:justify-between">
      <div>
        Showing {startItem()}-{endItem()} of {props.totalItems} {itemLabel()}
      </div>
      <div class="flex items-center gap-2">
        <Button
          size="compact"
          type="button"
          disabled={props.page <= 1}
          onClick={() => props.onPageChange(Math.max(1, props.page - 1))}
        >
          Previous
        </Button>
        <span class="min-w-16 text-center text-gray-300">
          {props.page} / {totalPages()}
        </span>
        <Button
          size="compact"
          type="button"
          disabled={props.page >= totalPages()}
          onClick={() => props.onPageChange(Math.min(totalPages(), props.page + 1))}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
