import type { ValidComponent } from "solid-js";
import { splitProps } from "solid-js";
import type { PolymorphicProps } from "@kobalte/core/polymorphic";
import * as Primitive from "@kobalte/core/collapsible";
import { cn } from "~/lib/utils";

const Collapsible = Primitive.Root;
const CollapsibleTrigger = Primitive.Trigger;

function CollapsibleContent<T extends ValidComponent = "div">(
  props: PolymorphicProps<T, Primitive.CollapsibleContentProps<T> & { class?: string }>,
) {
  const [local, others] = splitProps(props as Primitive.CollapsibleContentProps & { class?: string }, ["class"]);
  return <Primitive.Content class={cn("overflow-hidden", local.class)} {...others} />;
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
