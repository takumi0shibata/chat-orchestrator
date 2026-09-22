import { describe, expect, it } from "vitest";

import type { Skill } from "../types";
import {
  exactSkillMatch,
  findSkillMention,
  matchingSkills,
  replaceSkillMention,
  skillMentionName,
} from "./skillMention";

const skills: Skill[] = [
  { id: "review", label: "Academic review", name: "academic-writing", description: "Review drafts" },
  { id: "brief", label: "Morning brief", name: "morning-brief", description: "Prepare a brief" },
];

describe("skill mentions", () => {
  it("finds mentions only at a text boundary and the current cursor", () => {
    expect(findSkillMention("Use @acad", 9)).toEqual({ start: 4, end: 9, query: "acad" });
    expect(findSkillMention("@morning-brief", 14)).toEqual({ start: 0, end: 14, query: "morning-brief" });
    expect(findSkillMention("mail@example.com", 16)).toBeNull();
    expect(findSkillMention("@skill later", 12)).toBeNull();
  });

  it("matches names, ids, and labels with exact matches first", () => {
    expect(matchingSkills(skills, "acad").map((skill) => skill.id)).toEqual(["review"]);
    expect(matchingSkills(skills, "review").map((skill) => skill.id)).toEqual(["review"]);
    expect(exactSkillMatch(skills, "ACADEMIC-WRITING")?.id).toBe("review");
    expect(exactSkillMatch(skills, "missing")).toBeNull();
  });

  it("removes a selected mention without leaving doubled whitespace", () => {
    expect(replaceSkillMention("Use @academic-writing for this", { start: 4, end: 21, query: "academic-writing" }))
      .toEqual({ value: "Use for this", cursor: 4 });
    expect(replaceSkillMention("@academic-writing Review this", { start: 0, end: 17, query: "academic-writing" }))
      .toEqual({ value: "Review this", cursor: 0 });
    expect(replaceSkillMention("@academic-writing", { start: 0, end: 17, query: "academic-writing" }))
      .toEqual({ value: "", cursor: 0 });
  });

  it("falls back to the configured id for non-token skill names", () => {
    expect(skillMentionName({ ...skills[0], name: "Academic writing" })).toBe("review");
  });
});
