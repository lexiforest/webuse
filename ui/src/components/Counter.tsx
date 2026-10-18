import { createSignal } from "solid-js";

import { Button } from "~/components/ui/button";

export default function Counter() {
  const [count, setCount] = createSignal(0);
  return (
    <Button class="w-[200px]" onClick={() => setCount(count() + 1)}>
      Clicks: {count()}
    </Button>
  );
}
