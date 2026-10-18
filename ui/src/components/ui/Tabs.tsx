// Adapted from stefan-karger/solid-ui. See public/THIRD_PARTY_NOTICES.md.
import type { ValidComponent } from "solid-js";
import { splitProps } from "solid-js";
import type { PolymorphicProps } from "@kobalte/core/polymorphic";
import * as Primitive from "@kobalte/core/tabs";
import { cn } from "~/lib/utils";

function Tabs<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, Primitive.TabsRootProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.TabsRootProps & { class?: string }, ["class"]);
  return <Primitive.Root class={cn("flex min-w-0 flex-col gap-4", local.class)} {...others} />;
}
type TabsListStyleProps = { class?: string; variant?: "default" | "line" };

function TabsList<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, Primitive.TabsListProps<T> & TabsListStyleProps>,
) {
  const [local, others] = splitProps(props as Primitive.TabsListProps & TabsListStyleProps, [
    "class",
    "variant",
  ]);
  return (
    <Primitive.List
      data-variant={local.variant ?? "default"}
      class={cn(
        "inline-flex h-9 w-fit shrink-0 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground",
        local.variant === "line" &&
          "rounded-none bg-transparent p-0 [&_[role=tab]]:h-full [&_[role=tab]]:rounded-none [&_[role=tab]]:border-b-2 [&_[role=tab]]:border-transparent [&_[role=tab]]:bg-transparent [&_[role=tab]]:shadow-none [&_[role=tab][data-selected]]:border-primary",
        local.class,
      )}
      {...others}
    />
  );
}

function TabsTrigger<T extends ValidComponent = "button">(
  props: PolymorphicProps<T, Primitive.TabsTriggerProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.TabsTriggerProps & { class?: string }, [
    "class",
  ]);
  return (
    <Primitive.Trigger
      class={cn(
        "inline-flex h-full shrink-0 items-center justify-center whitespace-nowrap rounded-sm px-3 py-2 text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[selected]:bg-background data-[selected]:text-foreground data-[selected]:shadow-sm",
        local.class,
      )}
      {...others}
    />
  );
}

function TabsContent<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, Primitive.TabsContentProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.TabsContentProps & { class?: string }, [
    "class",
  ]);
  return (
    <Primitive.Content
      class={cn(
        "min-w-0 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        local.class,
      )}
      {...others}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
