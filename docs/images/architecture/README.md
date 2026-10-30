# Architecture diagrams

The architecture guide embeds PNG images so readers can see the diagrams in
GitHub Mobile and Markdown viewers without Mermaid rendering. Each image links
to its full-size version; the adjacent `.mmd` file is its editable source.

Regenerate both images after editing their source. Use the standard Mermaid CLI
**12.0.0** with Node.js 22.13 or newer and its supported browser setup:

```sh
npm exec --yes --package @mermaid-js/mermaid-cli@12.0.0 -- mmdc -i docs/images/architecture/components.mmd -o docs/images/architecture/components.png -t neutral -b white -s 2
npm exec --yes --package @mermaid-js/mermaid-cli@12.0.0 -- mmdc -i docs/images/architecture/analysis-sequence.mmd -o docs/images/architecture/analysis-sequence.png -t neutral -b white -s 2
```

Run from the repository root. The white background keeps labels and connectors
readable in both light and dark viewers. Inspect both outputs at full size and
at a narrow page width before committing the source and images together.
These are documentation assets; they are not included in Studio's runtime.
