import type { ComponentProps, ValidComponent } from "solid-js";
import { splitProps } from "solid-js";
import { Tabs as TabsPrimitive } from "@kobalte/core/tabs";

function cx(...classes: Array<string | undefined | false>) {
  return classes.filter(Boolean).join(" ");
}

export type TabsProps<T extends ValidComponent = "div"> = ComponentProps<
  typeof TabsPrimitive<T>
>;

export const Tabs = <T extends ValidComponent = "div">(props: TabsProps<T>) => {
  const [, rest] = splitProps(props as TabsProps, ["class"]);

  return (
    <TabsPrimitive
      data-slot="tabs"
      class={cx("flex min-w-0 flex-col gap-4", props.class)}
      {...rest}
    />
  );
};

export type TabsListProps<T extends ValidComponent = "div"> = ComponentProps<
  typeof TabsPrimitive.List<T>
>;

export const TabsList = <T extends ValidComponent = "div">(props: TabsListProps<T>) => {
  const [, rest] = splitProps(props as TabsListProps, ["class"]);

  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      class={cx(
        "inline-flex h-9 w-fit items-center justify-center rounded-lg bg-gray-800 p-[3px] text-gray-400",
        props.class,
      )}
      {...rest}
    />
  );
};

export type TabsTriggerProps<T extends ValidComponent = "button"> = ComponentProps<
  typeof TabsPrimitive.Trigger<T>
>;

export const TabsTrigger = <T extends ValidComponent = "button">(
  props: TabsTriggerProps<T>,
) => {
  const [, rest] = splitProps(props as TabsTriggerProps, ["class"]);

  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      class={cx(
        "inline-flex h-[calc(100%-1px)] cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent bg-transparent px-3 py-1 text-sm font-medium text-gray-400 transition-colors hover:text-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 disabled:pointer-events-none disabled:opacity-50 data-[selected]:bg-gray-950 data-[selected]:text-gray-50 data-[selected]:shadow-sm",
        props.class,
      )}
      {...rest}
    />
  );
};

export type TabsContentProps<T extends ValidComponent = "div"> = ComponentProps<
  typeof TabsPrimitive.Content<T>
>;

export const TabsContent = <T extends ValidComponent = "div">(
  props: TabsContentProps<T>,
) => {
  const [, rest] = splitProps(props as TabsContentProps, ["class"]);

  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      class={cx("min-w-0 outline-none", props.class)}
      {...rest}
    />
  );
};
