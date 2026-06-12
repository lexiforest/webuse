import { createSignal } from "solid-js";

import Button from "./Button";

export default function Counter() {
  const [count, setCount] = createSignal(0);
  return (
    <Button class="w-[200px]" onClick={() => setCount(count() + 1)}>
      Clicks: {count()}
    </Button>
  );
}
