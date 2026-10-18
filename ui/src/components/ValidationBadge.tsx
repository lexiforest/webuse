import { Show } from "solid-js";

export default function ValidationBadge(props: { metadata?: Record<string, unknown> }) {
  return (
    <Show when={props.metadata?.assistantSample}>
      <span
        title="Automatically started by Harness to validate the crawler"
        aria-label="Validation: automatically started by Harness"
        class="inline-flex shrink-0 rounded border border-violet-400/30 bg-violet-400/10 px-1.5 py-0.5 text-[0.65rem] font-medium normal-case tracking-normal text-violet-300"
      >
        Validation
      </span>
    </Show>
  );
}
