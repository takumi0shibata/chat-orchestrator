import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SkillBlockRenderer } from "./SkillBlockRenderer";

describe("SkillBlockRenderer", () => {
  it("renders chart and card list blocks and emits generic feedback actions", async () => {
    const user = userEvent.setup();
    const onFeedback = vi.fn();

    render(
      <SkillBlockRenderer
        blocks={[
          {
            type: "line_chart",
            title: "全国CPI",
            frequency: "M",
            points: [
              { time: "2024-01", value: 101.2, raw: "101.2" },
              { time: "2024-02", value: 101.8, raw: "101.8" }
            ]
          },
          {
            type: "card_list",
            title: "監査アクションニュース",
            sections: [
              {
                id: "self_company",
                title: "自社",
                badge: { label: "1件", tone: "medium" },
                empty_message: "探索結果は0件でした。",
                items: [
                  {
                    id: "news-1",
                    title: "重要ニュース",
                    badge: { label: "自社", tone: "medium" },
                    metadata: [
                      { label: "Source", value: "NIKKEI" },
                      { label: "Published", value: "2026-03-01" }
                    ],
                    lines: [
                      { label: "概要", value: "業績見通しを下方修正。" },
                      { label: "一言コメント", value: "評価前提の見直しが必要。" }
                    ],
                    links: [{ label: "Source", url: "https://example.com/news-1" }],
                    actions: [
                      {
                        type: "feedback",
                        run_id: "run-1",
                        item_id: "news-1",
                        selected: null,
                        choices: [
                          { label: "対応する", value: "acted" },
                          { label: "様子見", value: "monitor" }
                        ]
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]}
        onFeedback={onFeedback}
      />
    );

    expect(screen.getByLabelText("全国CPI 時系列")).toBeInTheDocument();
    expect(screen.getByText("監査アクションニュース")).toBeInTheDocument();
    expect(screen.getByText("重要ニュース")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "対応する" }));
    expect(onFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: "run-1", item_id: "news-1" }),
      expect.objectContaining({ value: "acted" })
    );
  });

  it("disables already selected feedback actions", () => {
    render(
      <SkillBlockRenderer
        blocks={[
          {
            type: "card_list",
            title: "Selected",
            sections: [
              {
                id: "self_company",
                title: "自社",
                badge: { label: "1件", tone: "medium" },
                items: [
                  {
                    id: "news-1",
                    title: "重要ニュース",
                    metadata: [],
                    lines: [],
                    links: [],
                    actions: [
                      {
                        type: "feedback",
                        run_id: "run-1",
                        item_id: "news-1",
                        selected: "acted",
                        choices: [{ label: "対応する", value: "acted" }]
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]}
      />
    );

    expect(screen.getByRole("button", { name: "対応する" })).toBeDisabled();
  });

  it("keeps audit news badges present even when the title is long", () => {
    render(
      <SkillBlockRenderer
        blocks={[
          {
            type: "card_list",
            sections: [
              {
                id: "self_company",
                title: "自社",
                items: [
                  {
                    id: "news-long",
                    title:
                      "Memory chipmaker Kioxia, retail operator Pan Pacific to be added to Nikkei index and this headline is intentionally long to stress the layout",
                    badge: { label: "自社", tone: "medium" },
                    metadata: [],
                    lines: [],
                    links: [],
                    actions: []
                  }
                ]
              }
            ]
          }
        ]}
      />
    );

    const chips = screen.getAllByText("自社");
    expect(chips).toHaveLength(2);
    expect(chips[1]).toHaveClass("priority-chip", "medium");
  });
});
