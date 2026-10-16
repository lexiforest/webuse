import type { APIRoute } from "astro";
import human from "../../../../HUMAN.md?raw";

export function getStaticPaths() {
  return [
    { params: { name: "HUMAN" }, props: { content: human } },
  ];
}

export const GET: APIRoute = ({ props }) =>
  new Response(props.content, {
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
