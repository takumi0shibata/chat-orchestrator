import type { Skill } from "../types";

export interface SkillMention {
  start: number;
  end: number;
  query: string;
}

export function skillMentionName(skill: Skill): string {
  return /^[a-zA-Z0-9_-]{1,64}$/.test(skill.name) ? skill.name : skill.id;
}

export function findSkillMention(value: string, cursor: number): SkillMention | null {
  if (cursor < 0 || cursor > value.length) return null;
  const match = /(^|\s)@([a-zA-Z0-9_-]*)$/.exec(value.slice(0, cursor));
  if (!match) return null;
  return {
    start: match.index + match[1].length,
    end: cursor,
    query: match[2],
  };
}

function matchRank(skill: Skill, query: string): number | null {
  const values = [skillMentionName(skill), skill.name, skill.id, skill.label]
    .map((value) => value.toLocaleLowerCase());
  const normalized = query.toLocaleLowerCase();
  if (!normalized) return 2;
  if (values.includes(normalized)) return 0;
  if (values.some((value) => value.startsWith(normalized))) return 1;
  return null;
}

export function matchingSkills(skills: Skill[], query: string): Skill[] {
  return skills
    .map((skill) => ({ skill, rank: matchRank(skill, query) }))
    .filter((item): item is { skill: Skill; rank: number } => item.rank !== null)
    .sort((left, right) =>
      left.rank - right.rank ||
      skillMentionName(left.skill).localeCompare(skillMentionName(right.skill)),
    )
    .map(({ skill }) => skill);
}

export function exactSkillMatch(skills: Skill[], query: string): Skill | null {
  const normalized = query.toLocaleLowerCase();
  if (!normalized) return null;
  return skills.find((skill) =>
    [skillMentionName(skill), skill.name, skill.id, skill.label]
      .some((value) => value.toLocaleLowerCase() === normalized),
  ) || null;
}

export function replaceSkillMention(
  value: string,
  mention: SkillMention,
): { value: string; cursor: number } {
  const before = value.slice(0, mention.start);
  let after = value.slice(mention.end);

  if (!before && /^\s/.test(after)) after = after.slice(1);
  else if (/\s$/.test(before) && /^\s/.test(after)) after = after.slice(1);

  return { value: before + after, cursor: before.length };
}
