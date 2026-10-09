export type GuildPeriod = "morning" | "day" | "evening" | "night";

// Use the browser's local clock, like the timestamps elsewhere in the app.
export function guildPeriod(date = new Date()): GuildPeriod {
  const hour = date.getHours();
  if (hour >= 5 && hour < 11) return "morning";
  if (hour >= 11 && hour < 17) return "day";
  if (hour >= 17 && hour < 20) return "evening";
  return "night";
}

export function nextGuildPeriodDelay(date = new Date()): number {
  const next = new Date(date);
  const hour = [5, 11, 17, 20].find((boundary) => boundary > date.getHours());
  if (hour === undefined) next.setDate(next.getDate() + 1);
  next.setHours(hour ?? 5, 0, 0, 0);
  return Math.max(1, next.getTime() - date.getTime());
}

export const guildDay = {
  morning: {
    label: "Morning", activity: "Getting ready for the day",
    comments: ["おはようございます。今日も一つずつ。", "まずは今日の依頼を、のぞいてみましょう。", "出発前に、お茶を一杯いかがですか？"],
  },
  day: {
    label: "Daytime", activity: "Delivering the day's quests",
    comments: ["こんにちは。どの依頼から始めましょう？", "少し進んだら、ひと息つくのも大事です。", "新しい記録があれば、Syncで届けてください。"],
  },
  evening: {
    label: "Evening", activity: "Taking the evening rounds",
    comments: ["夕暮れですね。ギルドに灯りをともしました。", "今日の気づき、日誌に残しておきませんか？", "残った依頼は、明日の道しるべにもなります。"],
  },
  night: {
    label: "Night", activity: "Tea and a little rest",
    comments: ["夜のギルドは静かですね。温かいお茶をどうぞ。", "続きは明日でも。ここで少し休みましょう。", "猫もすっかり夢の中です。おやすみなさい。"],
  },
} satisfies Record<GuildPeriod, { label: string; activity: string; comments: string[] }>;
