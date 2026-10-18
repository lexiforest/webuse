// Adapted from stefan-karger/solid-ui. See public/THIRD_PARTY_NOTICES.md.
import type { JSX, ValidComponent } from "solid-js";
import { splitProps } from "solid-js";
import * as SelectPrimitive from "@kobalte/core/select";
import type { PolymorphicProps } from "@kobalte/core/polymorphic";
import { cn } from "~/lib/utils";

const Select = SelectPrimitive.Root;
const SelectValue = SelectPrimitive.Value;

function SelectLabel(props: SelectPrimitive.SelectLabelProps & { class?: string; children?: JSX.Element }) {
  const [local, others] = splitProps(props, ["class"]);
  return <SelectPrimitive.Label class={cn("text-sm font-medium text-muted-foreground", local.class)} {...others} />;
}

type SelectTriggerProps<T extends ValidComponent = "button"> =
  SelectPrimitive.SelectTriggerProps<T> & {
    class?: string;
    children?: JSX.Element;
  };

function SelectTrigger<T extends ValidComponent = "button">(
  props: PolymorphicProps<T, SelectTriggerProps<T>>,
) {
  const [local, others] = splitProps(props as SelectTriggerProps, ["class", "children"]);

  return (
    <SelectPrimitive.Trigger
      class={cn(
        "flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm text-foreground ring-offset-background transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        local.class,
      )}
      {...others}
    >
      {local.children}
      <SelectPrimitive.Icon
        as="svg"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="size-4 shrink-0 opacity-50"
        aria-hidden="true"
      >
        <path d="m8 9 4-4 4 4" />
        <path d="m16 15-4 4-4-4" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

type SelectContentProps<T extends ValidComponent = "div"> =
  SelectPrimitive.SelectContentProps<T> & {
    class?: string;
  };

function SelectContent<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, SelectContentProps<T>>,
) {
  const [local, others] = splitProps(props as SelectContentProps, ["class"]);

  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        class={cn(
          "relative z-50 min-w-32 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md",
          local.class,
        )}
        {...others}
      >
        <SelectPrimitive.Listbox class="m-0 p-1" />
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

type SelectItemProps<T extends ValidComponent = "li"> = SelectPrimitive.SelectItemProps<T> & {
  class?: string;
  children?: JSX.Element;
};

function SelectItem<T extends ValidComponent = "li">(
  props: PolymorphicProps<T, SelectItemProps<T>>,
) {
  const [local, others] = splitProps(props as SelectItemProps, ["class", "children"]);

  return (
    <SelectPrimitive.Item
      class={cn(
        "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pr-8 pl-2 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
        local.class,
      )}
      {...others}
    >
      <SelectPrimitive.ItemLabel>{local.children}</SelectPrimitive.ItemLabel>
      <span class="absolute right-2 flex size-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="size-4"
            aria-hidden="true"
          >
            <path d="m5 12 5 5L20 7" />
          </svg>
        </SelectPrimitive.ItemIndicator>
      </span>
    </SelectPrimitive.Item>
  );
}

export { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue };
