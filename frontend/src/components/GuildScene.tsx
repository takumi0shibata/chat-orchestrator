import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { guildDay, guildPeriod, nextGuildPeriodDelay } from "../lib/guildTime";

const MOTION_KEY = "guild-scene-motion";

// A small SVG scene: no game engine, image downloads or JavaScript frame loop.
function Adventurer({ resting }: { resting: boolean }) {
  return <g>
    <g className="guild-pixel-body">
      <path fill="#243e39" d="M4 10h12v13H4z" />
      <path fill="#79aa72" d="M5 13h10v8H5zM6 0h8v2H6zM3 2h14v5H3zM1 6h18v3H1z" />
      <path fill="#e2c091" d="M6 9h8v5H6zM2 15h3v5H2zM15 15h3v5h-3z" />
      <path fill="#3b322d" d={resting ? "M7 10h2v1H7zM12 10h2v1h-2z" : "M7 9h2v2H7zM12 9h2v2h-2z"} />
      <path fill="#c1974e" d="M5 18h10v3H5zM13 2h2v5h-2z" />
      {resting ? <>
        <path fill="#efdfb4" d="M16 16h5v5h-5zM21 17h2v3h-2z" />
        <path className="guild-tea-steam" fill="#d6d7c5" d="M17 12h1v2h-1zM19 10h1v3h-1z" />
      </> : <><path fill="#efdfb4" d="M16 13h5v8h-5z" /><path fill="#a98954" d="M17 15h3v1h-3zM17 18h2v1h-2z" /></>}
    </g>
    <path className="guild-pixel-foot guild-pixel-foot-left" fill="#322b29" d="M4 22h5v4H3v-2h1z" />
    <path className="guild-pixel-foot guild-pixel-foot-right" fill="#322b29" d="M11 22h5v4h2v2h-7z" />
  </g>;
}

export function GuildScene() {
  const [paused, setPaused] = useState(() => {
    try { return localStorage.getItem(MOTION_KEY) === "paused"; } catch { return false; }
  });
  const [visible, setVisible] = useState(!document.hidden);
  const [inView, setInView] = useState(false);
  const [reduced, setReduced] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  const [period, setPeriod] = useState(() => guildPeriod());
  const [comment, setComment] = useState(0);
  const scene = useRef<HTMLDivElement>(null);
  const running = !paused && visible && inView && !reduced;
  const day = guildDay[period];
  useEffect(() => {
    const visibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", visibility);
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const preference = () => setReduced(media?.matches ?? false);
    media?.addEventListener("change", preference);
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(
      (entries) => setInView(entries.some((entry) => entry.isIntersecting)),
      { threshold: 0 },
    );
    if (scene.current) observer?.observe(scene.current);
    if (!observer) setInView(true);
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      media?.removeEventListener("change", preference);
      observer?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!visible || !inView) return;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = () => {
      const now = new Date();
      setPeriod(guildPeriod(now));
      clearTimeout(timer);
      // One wake-up at the next period boundary, never a polling or frame loop.
      timer = setTimeout(refresh, nextGuildPeriodDelay(now));
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { clearTimeout(timer); window.removeEventListener("focus", refresh); };
  }, [visible, inView]);

  function nextComment() { setComment((index) => (index + 1) % day.comments.length); }

  function toggleMotion() {
    const next = !paused;
    setPaused(next);
    try { localStorage.setItem(MOTION_KEY, next ? "paused" : "running"); } catch { /* Optional preference storage. */ }
  }

  return <div ref={scene} className="guild-scene" data-period={period} data-motion={running ? "running" : "paused"}>
    <div className="guild-scene-label"><span>GUILD CORNER</span><span>{day.label}</span></div>
    <svg className="guild-room" viewBox="0 0 288 112" aria-hidden="true" focusable="false" shapeRendering="crispEdges">
      {/* The room is drawn on a small pixel grid, then scaled by the browser. */}
      <path fill="var(--room-frame)" d="M0 0h288v112H0z" />
      <path fill="var(--room-wall)" d="M0 7h288v65H0z" />
      <path fill="var(--room-brick)" d="M8 12h52v3H8zM66 12h48v3H66zM120 12h52v3h-52zM178 12h54v3h-54zM238 12h42v3h-42zM20 32h53v2H20zM85 32h42v2H85zM160 32h42v2h-42zM14 53h46v2H14zM80 53h64v2H80zM162 53h54v2h-54z" />
      <path fill="var(--room-floor)" d="M0 70h288v42H0z" />
      <path fill="var(--room-floor-line)" d="M0 72h288v2H0zM0 85h288v2H0zM0 101h288v2H0z" />
      <path fill="#513b2e" d="M51 74h2v11h-2zM124 74h2v11h-2zM230 74h2v11h-2zM27 87h2v14h-2zM168 87h2v14h-2zM260 87h2v14h-2zM89 103h2v9h-2zM210 103h2v9h-2z" />
      <path fill="var(--room-frame)" d="M0 0h288v7H0zM0 7h8v65H0zM280 7h8v65h-8z" />
      {/* Door, notice board and a window looking out over the hills. */}
      <path fill="#29362f" d="M14 25h28v47H14z" /><path fill="#906342" d="M18 29h20v41H18z" />
      <path fill="#60472f" d="M22 31h2v39h-2zM31 31h2v39h-2z" /><path fill="#e4bf71" d="M33 50h3v3h-3z" />
      <path fill="#b08750" d="M52 23h63v41H52z" /><path fill="#614b32" d="M56 27h55v33H56z" />
      <path fill="#ece0b9" d="M61 32h15v20H61zM83 31h20v13H83zM84 48h14v8H84z" />
      <path fill="#b29b75" d="M65 37h7v2h-7zM65 42h8v2h-8zM87 35h12v2H87zM87 39h7v1h-7z" />
      <path fill="#9f5942" d="M67 30h3v3h-3zM91 29h3v3h-3zM89 47h3v3h-3z" />
      <path fill="#b39760" d="M214 14h48v46h-48z" /><path fill="var(--room-sky)" d="M218 18h40v38h-40z" />
      {period === "night" ? <>
        <path fill="#eee8c2" d="M243 21h7v3h-3v4h3v3h-7v-3h-2v-4h2z" />
        <path fill="#c7d4dd" d="M223 23h2v2h-2zM231 29h2v2h-2zM253 34h2v2h-2z" />
      </> : <path className="guild-sun" fill="var(--room-sun)" d="M242 22h7v7h-7z" />}
      <path fill="var(--room-hills)" d="M218 44h6v-5h8v-5h6v7h8v4h12v11h-40z" />
      <path fill="var(--room-trees)" d="M218 49h8v-4h10v4h10v-6h5v7h7v6h-40z" />
      <path fill="#705436" d="M236 18h3v38h-3zM218 36h40v3h-40zM210 58h56v4h-56z" />
      {/* Hanging guild banner and lantern. */}
      <path fill="#a6b388" d="M170 16h26v32h-5v5h-6v4h-4v-4h-6v-5h-5z" />
      <path fill="#435d4c" d="M179 25h9v3h-9zM182 22h3v18h-3zM176 32h15v3h-15z" />
      <path fill="#c2a05c" d="M168 13h30v3h-30zM138 7h2v12h-2z" />
      <path fill="#544e40" d="M132 19h14v18h-14z" /><path fill="var(--room-lantern)" d="M135 22h8v12h-8z" /><path fill="var(--room-lantern-core)" d="M137 24h4v8h-4z" />
      {/* Rug, a plant and the guild master's counter. */}
      <path fill="#3e5143" d="M66 89h140v18H66z" /><path fill="#a39460" d="M69 91h134v2H69zM69 103h134v2H69zM69 93h2v10h-2zM201 93h2v10h-2z" />
      <path fill="#688455" d="M268 47h6v15h-6zM262 51h6v5h-6zM274 44h5v7h-5z" /><path fill="#b38155" d="M264 61h13v10h-13z" />
      <g transform="translate(224 61)"><g className="guild-clerk-bob">
        <path fill="#352c2e" d="M2 1h13v11H2z" /><path fill="#d5ad80" d="M4 6h10v9H4z" />
        <path fill="#e7dcb5" d="M1 0h15v4H1zM4 4h9v2H4z" />
        <path fill="#343333" d="M5 8h2v2H5zM10 8h2v2h-2z" />
        <path fill="#9b684b" d="M1 15h16v13H1z" /><path fill="#e1ca98" d="M5 15h8v8H5z" />
      </g></g>
      <path fill="#3c3028" d="M211 82h59v23h-59z" /><path fill="#ae8350" d="M207 79h67v6h-67z" />
      <path fill="#785538" d="M215 88h51v14h-51z" /><path fill="#c3a067" d="M237 90h7v7h-7z" />
      <path fill="#eee0bd" d="M249 75h15v4h-15zM216 77h12v2h-12z" />
      {/* The courier walks; only these small groups are animated. */}
      <g transform="translate(32 72)"><g className="guild-courier-route"><g className="guild-courier-facing"><Adventurer resting={period === "night"} /></g></g></g>
      <g transform="translate(176 91)"><g className="guild-cat-bob">
        <path fill="#d4a76b" d="M1 3h12v9H1zM2 0h3v4H2zM9 0h3v4H9zM4 10h14v5H4z" />
        <path fill="#3c3830" d={period === "night" ? "M2 6h3v1H2zM9 6h3v1H9z" : "M3 5h2v2H3zM9 5h2v2H9z"} /><path fill="#efcf98" d="M6 8h2v3H6z" />
        <path className="guild-cat-tail" fill="#d4a76b" d="M15 7h3v7h-3zM17 4h3v5h-3z" />
      </g></g>
      {period === "night" && <path className="guild-sleep" fill="#c3c7c9" d="M190 84h5v1h-2v2h-2v1h4v1h-5v-2h2v-2h-2z" />}
    </svg>
    <button key={period} className="guild-speech" type="button" lang="ja" title="Another comment" onClick={nextComment} onAnimationIteration={(event) => {
      if (event.target === event.currentTarget && running) nextComment();
    }}>{day.comments[comment]}<span aria-hidden="true">···</span></button>
    <div className="guild-scene-caption"><span>{day.activity}</span><button type="button" onClick={toggleMotion} disabled={reduced} aria-label={reduced ? "Scene motion reduced by system preference" : paused ? "Resume scene animation" : "Pause scene animation"}>
      {paused || reduced ? <Play size={11} /> : <Pause size={11} />}{reduced ? "Reduced motion" : paused ? "Resume" : "Pause"}
    </button></div>
  </div>;
}
