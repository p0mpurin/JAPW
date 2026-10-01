// Offset-paged feed backed by the server's read-ahead cache (home, For You, search, boards, artists).
import { api, errorMessage } from "../core/api.js";
import { state } from "../core/state.js";
import { on } from "../core/bus.js";
import { SWATCHES } from "../core/colors.js";
import { renderPosts, appendPosts, visibleCount, showSkeleton } from "../gallery.js";
import { ensureBuffer, scheduleScrollCheck } from "../infinite.js";
import { setSentinelVisible, setInfiniteLoading, hideEmpty } from "../ui/feedback.js";
import { setProgress } from "../ui/viewbar.js";

/** Keep pulling pages in the background until this many cards are visible. */
const FILL_UNTIL = 40;

/**
 * pageUrl(offset) → API path. Hooks: onEmpty(), onError(res, message), onLoaded(res).
 * colorAware: the server filters by the active colour (&color=…), so a colour change restarts
 * the feed instead of hiding cards client-side.
 * Results that arrive after a tab switch are kept (so returning is instant) but not drawn.
 */
export function createPagedFeed({ tab, pageUrl, onEmpty, onError, onLoaded, colorAware = false }) {
  const feed = {
    posts: [],
    offset: 0,
    exhausted: false,
    loading: false,
    epoch: 0,
    started: false,
    color: null,
  };
  feed.isCurrent = () => true;
  const visible = () => state.tab === tab && feed.isCurrent();

  const url = (offset) => {
    const base = pageUrl(offset);
    return colorAware && feed.color ? `${base}&color=${feed.color}` : base;
  };

  function progressText() {
    if (!feed.color) return "Loading…";
    const s = SWATCHES.find((x) => x.id === feed.color);
    return `Finding ${s ? s.label.toLowerCase() : ""} pins…`;
  }

  function absorb(res) {
    const posts = res.data.posts || [];
    feed.posts.push(...posts);
    feed.offset = res.data.next_offset ?? feed.offset + posts.length;
    feed.exhausted = !res.data.has_more;
    return posts;
  }

  feed.start = async () => {
    const epoch = ++feed.epoch;
    feed.color = colorAware ? state.colorFilter : null;
    Object.assign(feed, { posts: [], offset: 0, exhausted: false, loading: true, started: true });
    if (visible()) {
      state.serverColor = colorAware;
      hideEmpty();
      showSkeleton();
      setProgress(feed.color ? progressText() : null);
    }
    const res = await api.get(url(0)).catch(() => null);
    if (epoch !== feed.epoch) return;
    feed.loading = false;
    if (visible()) setProgress(null);
    if (!res || !res.ok) {
      feed.started = false;
      if (visible()) {
        renderPosts([]);
        onError(res, errorMessage(res, "Check your connection and try again."));
      }
      if (onLoaded) onLoaded(res);
      return;
    }
    const posts = absorb(res);
    if (visible()) {
      renderPosts(posts);
      if (posts.length) afterPage();
      else if (feed.exhausted) onEmpty();
      else feed.more();
    }
    if (onLoaded) onLoaded(res);
  };

  feed.more = async () => {
    if (feed.loading || feed.exhausted || !feed.started) return;
    feed.loading = true;
    const epoch = feed.epoch;
    if (visible()) {
      setInfiniteLoading(true);
      if (feed.color && visibleCount() < FILL_UNTIL) setProgress(progressText());
    }
    const res = await api.get(url(feed.offset)).catch(() => null);
    feed.loading = false;
    if (epoch !== feed.epoch) return;
    if (visible()) {
      setInfiniteLoading(false);
      setProgress(null);
    }
    if (!res || !res.ok) return; // stays resumable: the next scroll retries
    const posts = absorb(res);
    if (!visible()) return;
    appendPosts(posts);
    if (!feed.posts.length && feed.exhausted) onEmpty();
    else afterPage();
  };

  function afterPage() {
    setSentinelVisible(!feed.exhausted);
    if (feed.exhausted) return;
    scheduleScrollCheck();
    ensureBuffer();
    if (visibleCount() < FILL_UNTIL) setTimeout(() => visible() && feed.more(), 30);
  }

  /** Redraw what we already have (returning to the tab). */
  feed.show = () => {
    if (colorAware && feed.color !== state.colorFilter) {
      feed.start();
      return;
    }
    state.serverColor = colorAware;
    if (feed.loading && !feed.posts.length) {
      showSkeleton();
      return;
    }
    renderPosts(feed.posts);
    afterPage();
  };

  if (colorAware) {
    on("color:changed", () => {
      if (visible() && feed.started) feed.start();
    });
  }

  return feed;
}
