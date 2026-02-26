# AI/ML/NLP Paper Review Rubric (Primary Sources)

This note captures high-trust review dimensions used by `paper_reviewer`.

## Primary Sources

- ACL Rolling Review CFP: https://aclrollingreview.org/cfp
- ACL Rolling Review Reviewer Guidelines: https://aclrollingreview.org/reviewerguidelines
- ACL Responsible NLP Checklist: https://aclrollingreview.org/responsibleNLPresearch/
- ICML 2026 Reviewer Instructions: https://icml.cc/Conferences/2026/ReviewerInstructions
- NeurIPS Paper Checklist: https://neurips.cc/public/guides/PaperChecklist
- NeurIPS Code/Data Policy: https://neurips.cc/public/guides/CodeSubmissionPolicy
- EMNLP 2025 Reproducibility Criteria: https://2025.emnlp.org/calls/papers/Reproducibility-Criteria

## Shared Core Dimensions

1. Claim-Evidence Alignment
- Verify whether key claims are directly supported by reported analyses and experiments.

2. Novelty and Positioning
- Check if the manuscript clarifies contribution boundaries vs prior work.

3. Soundness and Method Quality
- Check if assumptions, method details, and evaluation setup are internally coherent.

4. Clarity and Writing Quality
- Penalize ambiguous wording, overclaiming, and weak logical transitions.

5. Reproducibility
- Request concrete details on data splits, hyperparameter search, compute budget, and variance handling.

6. Limitations and Responsible Disclosure
- Ensure clear statement of limitations, failure modes, and possible downstream risks.

## Output Guidance for This Project

- Feedback language: Japanese by default.
- Revised text: keep input language (e.g., English draft stays English).
- Revisions: prefer minimal, local edits over full rewrites.
- When proposing edits, always include at least one LaTeX block:

```latex
% Revised sentence/paragraph
<revised text here>
```
