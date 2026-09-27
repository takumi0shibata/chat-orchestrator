declare module "markdown-it-texmath" {
  import type MarkdownIt from "markdown-it";
  import type { KatexOptions, renderToString } from "katex";

  export default function texmath(markdown: MarkdownIt, options: {
    engine: { renderToString: typeof renderToString };
    delimiters: string[];
    katexOptions?: KatexOptions;
  }): void;
}
