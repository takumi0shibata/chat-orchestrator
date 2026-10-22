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
    comments: ["Good morning. One step at a time.", "Let's take a look at today's quests.", "How about a cup of tea before setting out?"],
  },
  day: {
    label: "Daytime", activity: "Delivering the day's quests",
    comments: ["Hello! Which quest shall we start with?", "Remember to take a break when you've made some progress.", "New records to share? Bring them in with Sync."],
  },
  evening: {
    label: "Evening", activity: "Taking the evening rounds",
    comments: ["It's dusk. The guild lights are on.", "Shall we record today's discoveries in the journal?", "Unfinished quests can guide tomorrow's journey."],
  },
  night: {
    label: "Night", activity: "Tea and a little rest",
    comments: ["The guild is quiet tonight. Here's some warm tea.", "We can continue tomorrow. Rest here for a while.", "Even the cat is dreaming. Good night."],
  },
} satisfies Record<GuildPeriod, { label: string; activity: string; comments: string[] }>;
