import DOMPurify from "dompurify";
import { marked } from "marked";
import { For, Show } from "solid-js";
import { FiSend } from "solid-icons/fi";

import Button from "~/components/Button";

marked.setOptions({ async: false, breaks: true, gfm: true });

export type LLMChatMessage = {
  role: "user" | "assistant";
  content: string;
  metadata?: {
    changedFiles?: string[];
  };
};

type LLMChatProps = {
  messages?: LLMChatMessage[];
  value: string;
  pending?: boolean;
  loading?: boolean;
  disabled?: boolean;
  placeholder: string;
  emptyTitle: string;
  emptyDescription: string;
  userName?: string;
  assistantName?: string;
  pendingText?: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
};

function renderMarkdown(text: string) {
  if (!text) {
    return "";
  }
  const html = marked.parse(text) as string;
  const purify = DOMPurify as unknown as {
    sanitize?: (input: string, config?: Record<string, unknown>) => string;
  };
  return typeof purify.sanitize === "function"
    ? purify.sanitize(html, { USE_PROFILES: { html: true } })
    : html;
}

export default function LLMChat(props: LLMChatProps) {
  const userName = () => props.userName || "You";
  const assistantName = () => props.assistantName || "Assistant";

  function handleComposerKeyDown(event: KeyboardEvent) {
    if (event.key !== "Enter") {
      return;
    }
    if (event.isComposing || event.shiftKey) {
      return;
    }

    event.preventDefault();
    if (!props.disabled && !props.pending && props.value.trim()) {
      props.onSubmit();
    }
  }

  return (
    <>
      <div class="llm-messages">
        <Show
          when={!props.loading}
          fallback={<div class="text-sm text-gray-500">Loading messages...</div>}
        >
          <Show
            when={props.messages?.length || props.pending}
            fallback={
              <div class="llm-empty">
                <h2>{props.emptyTitle}</h2>
                <p>{props.emptyDescription}</p>
              </div>
            }
          >
            <For each={props.messages ?? []}>
              {message => (
                <article class={`llm-message ${message.role}`}>
                  <div class="llm-message-role">
                    {message.role === "user" ? userName() : assistantName()}
                  </div>
                  <div class="llm-message-body" innerHTML={renderMarkdown(message.content)} />
                  <Show when={message.metadata?.changedFiles?.length}>
                    <div class="llm-message-meta">
                      Changed: {message.metadata?.changedFiles?.join(", ")}
                    </div>
                  </Show>
                </article>
              )}
            </For>
            <Show when={props.pending}>
              <article class="llm-message assistant pending">
                <div class="llm-message-role">{assistantName()}</div>
                <div class="llm-thinking" aria-label={props.pendingText || "Thinking"}>
                  <span />
                  <span />
                  <span />
                </div>
              </article>
            </Show>
          </Show>
        </Show>
      </div>

      <div class="llm-composer">
        <textarea
          value={props.value}
          onInput={event => props.onValueChange(event.currentTarget.value)}
          onKeyDown={handleComposerKeyDown}
          placeholder={props.placeholder}
          disabled={props.disabled || props.pending || props.loading}
        />
        <Button
          aria-label="Send LLM message"
          disabled={props.disabled || !props.value.trim() || props.pending || props.loading}
          size="compact"
          type="button"
          onClick={props.onSubmit}
        >
          <FiSend size={13} stroke-width={2} aria-hidden="true" />
        </Button>
      </div>
    </>
  );
}
