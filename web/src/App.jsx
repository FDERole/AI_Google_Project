import { useEffect, useState } from "react";
import { useSanjaya } from "./store";
import Landing from "./pages/Landing";
import Phone from "./pages/Phone";
import Command from "./pages/Command";
import Teach from "./pages/Teach";
import { Eye } from "./components/Brand";

function useHash() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function Loading() {
  return <div className="grid h-full place-items-center"><Eye size={64} active /></div>;
}

// A "?muted" suffix on `me` keeps that view silent (the stage shows two phones on one computer).
function Connected({ me, children }) {
  const live = useSanjaya(me);
  if (!live.ready) return <Loading />;
  return children(live);
}

// One screen for recording the demo: two phones and the command center, live.
function Stage() {
  const [audio, setAudio] = useState("ravi");
  return (
    <div className="flex h-full flex-col bg-black">
      <div className="flex items-center justify-center gap-2 py-2 text-[12px] text-ink-400">
        Voice plays for
        {["arjun", "ravi"].map((u) => (
          <button key={u} onClick={() => setAudio(u)}
            className={`rounded-full px-3 py-1 font-semibold capitalize ${audio === u ? "bg-saffron-500 text-ink-950" : "bg-ink-800 text-ink-200"}`}>{u}</button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 items-stretch justify-center gap-5 px-5 pb-5">
        {["arjun", "ravi"].map((u, i) => (
          <div key={u} className={`w-[390px] shrink-0 rounded-[2.8rem] bg-ink-800 p-2.5 shadow-2xl ring-1 ring-ink-600 ${i === 1 ? "order-3" : ""}`}>
            <Connected me={audio === u ? u : `${u}?muted`}>{(live) => <Phone me={u} live={live} frame />}</Connected>
          </div>
        ))}
        <div className="order-2 min-w-0 flex-1">
          <Connected me="dashboard">{(live) => <Command live={live} compact />}</Connected>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const hash = useHash();
  const [, route, arg] = hash.split("/");
  if (route === "phone" && arg) {
    return (
      <div className="mx-auto h-full max-w-md">
        <Connected me={arg} key={arg}>{(live) => <Phone me={arg} live={live} />}</Connected>
      </div>
    );
  }
  if (route === "command") return <Connected me="dashboard">{(live) => <Command live={live} />}</Connected>;
  if (route === "teach") return <Connected me="meena?muted">{(live) => <Teach live={live} />}</Connected>;
  if (route === "stage") return <Stage />;
  return <Connected me="viewer">{(live) => <Landing live={live} />}</Connected>;
}
