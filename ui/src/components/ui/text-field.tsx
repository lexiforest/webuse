// Adapted from stefan-karger/solid-ui. See public/THIRD_PARTY_NOTICES.md.
import type { ValidComponent } from "solid-js";
import { splitProps } from "solid-js";
import type { PolymorphicProps } from "@kobalte/core/polymorphic";
import * as Primitive from "@kobalte/core/text-field";
import { cn } from "~/lib/utils";

function TextField<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, Primitive.TextFieldRootProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.TextFieldRootProps & { class?: string }, [
    "class",
  ]);
  return <Primitive.Root class={cn("flex min-w-0 flex-col gap-1.5", local.class)} {...others} />;
}
function TextFieldInput<T extends ValidComponent = "input">(
  props: PolymorphicProps<
    T,
    Primitive.TextFieldInputProps<T> & {
      class?: string;
      type?: "text" | "email" | "password" | "month" | "number";
    }
  >,
) {
  const [local, others] = splitProps(
    props as Primitive.TextFieldInputProps & {
      class?: string;
      type?: "text" | "email" | "password" | "month" | "number";
    },
    ["class", "type"],
  );
  return (
    <Primitive.Input
      type={local.type ?? "text"}
      class={cn(
        "flex h-10 w-full rounded-md border border-input bg-background text-foreground px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[invalid]:border-destructive",
        local.class,
      )}
      {...others}
    />
  );
}
function TextFieldLabel<T extends ValidComponent = "label">(
  props: PolymorphicProps<T, Primitive.TextFieldLabelProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.TextFieldLabelProps & { class?: string }, [
    "class",
  ]);
  return (
    <Primitive.Label
      class={cn("text-sm font-medium text-muted-foreground data-[invalid]:text-destructive", local.class)}
      {...others}
    />
  );
}
export { TextField, TextFieldInput, TextFieldLabel };
