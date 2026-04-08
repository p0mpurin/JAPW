(function () {
  "use strict";

  // ─── DOM refs ───
  var searchInput = document.getElementById("search-input");
  var searchBtn = document.getElementById("search-btn");
  var searchRow = document.getElementById("search-row");
  var topbarSpacer = document.getElementById("topbar-spacer");
  var tabHome = document.getElementById("tab-home");
  var tabSearch = document.getElementById("tab-search");
  var authBadge = document.getElementById("auth-badge");
  var settingsBtn = document.getElementById("settings-btn");
  var settingsPanel = document.getElementById("settings-panel");
  var settingsClose = document.getElementById("settings-close");
  var settingsBackdrop = document.getElementById("settings-backdrop");
  var folderInput = document.getElementById("download-folder");
  var folderPickerBtn = document.getElementById("folder-picker-btn");
  var resolutionFilterEnabledCb = document.getElementById("resolution-filter-enabled");
  var resolutionWidthInput = document.getElementById("resolution-width");
  var resolutionHeightInput = document.getElementById("resolution-height");
  var resolutionMatchModeSelect = document.getElementById("resolution-match-mode");
  var resolutionFilterSaveBtn = document.getElementById("resolution-filter-save-btn");

  var filterPromotedCb = document.getElementById("filter-promoted");
  var filterAiContentCb = document.getElementById("filter-ai-content");
  var pinterestStatus = document.getElementById("pinterest-status");
  var pinterestConnectBtn = document.getElementById("pinterest-connect-btn");
  var pinterestOpenBrowserBtn = document.getElementById("pinterest-open-browser-btn");
  var pinterestDisconnectBtn = document.getElementById("pinterest-disconnect-btn");
  var gallery = document.getElementById("gallery");
  var emptyState = document.getElementById("empty-state");
  var emptyTitleEl = document.getElementById("empty-title");
  var emptySubEl = document.getElementById("empty-sub");
  var loading = document.getElementById("loading");
  var modal = document.getElementById("modal");
  var modalImg = document.getElementById("modal-img");
  var modalVideo = document.getElementById("modal-video");
  var modalDownload = document.getElementById("modal-download");
  var modalClose = document.getElementById("modal-close");
  var modalPrev = document.getElementById("modal-prev");
  var modalNext = document.getElementById("modal-next");
  var modalDownloadAll = document.getElementById("modal-download-all");
  var modalBackdrop = modal.querySelector(".modal-backdrop");
  var modalContent = modal.querySelector(".modal-content");
  var modalStage = modal.querySelector(".modal-stage");
  var modalRelated = document.getElementById("modal-related");
  var modalSlideshowHint = document.getElementById("modal-slideshow-hint");
  var toast = document.getElementById("toast");
  var splash = document.getElementById("splash");
  var infiniteSentinel = document.getElementById("infinite-sentinel");
  var infiniteHint = document.getElementById("infinite-hint");
  var tabLiked = document.getElementById("tab-liked");
  var tabCollections = document.getElementById("tab-collections");
  var collectionsView = document.getElementById("collections-view");
  var bulkToggleBtn = document.getElementById("bulk-toggle-btn");
  var bulkBar = document.getElementById("bulk-bar");
  var bulkCountLabel = document.getElementById("bulk-count-label");
  var bulkDownloadBtn = document.getElementById("bulk-download-btn");
  var bulkClearBtn = document.getElementById("bulk-clear-btn");
  var searchHistoryDropdown = document.getElementById("search-history-dropdown");
  var colDialog = document.getElementById("col-dialog");
  var colDialogList = document.getElementById("col-dialog-list");
  var colDialogInput = document.getElementById("col-dialog-input");
  var colDialogCreateBtn = document.getElementById("col-dialog-create-btn");
  var colDialogClose = document.getElementById("col-dialog-close");
  var promptDialog = document.getElementById("prompt-dialog");
  var promptDialogTitle = document.getElementById("prompt-dialog-title");
  var promptDialogInput = document.getElementById("prompt-dialog-input");
  var promptDialogConfirm = document.getElementById("prompt-dialog-confirm");
  var promptDialogCancel = document.getElementById("prompt-dialog-cancel");
  var promptDialogClose = document.getElementById("prompt-dialog-close");
  var tabArtists = document.getElementById("tab-artists");
  var xFilterBar = document.getElementById("x-filter-bar");
  var xFilterPills = document.getElementById("x-filter-pills");
  var xManageBtn = document.getElementById("x-manage-btn");
  var xRefreshBtn = document.getElementById("x-refresh-btn");
  var xFetchBanner = document.getElementById("x-fetch-banner");
  var xFetchLabel = document.getElementById("x-fetch-label");
  var xPanel = document.getElementById("x-panel");
  var xPanelBackdrop = document.getElementById("x-panel-backdrop");
  var xPanelClose = document.getElementById("x-panel-close");
  var xAddInput = document.getElementById("x-add-input");
  var xAddBtn = document.getElementById("x-add-btn");
  var xArtistsList = document.getElementById("x-artists-list");
  var xSessionStatus = document.getElementById("x-session-status");
  var xSyncBtn = document.getElementById("x-sync-btn");
  var xDisconnectBtn = document.getElementById("x-disconnect-btn");
  var homeRefreshBtn = document.getElementById("home-refresh-btn");
  var gridZoomOut = document.getElementById("grid-zoom-out");
  var gridZoomIn = document.getElementById("grid-zoom-in");
  var gridZoomControls = document.getElementById("grid-zoom-controls");
  var modalSlideCounter = document.getElementById("modal-slide-counter");
  var modalDots = document.getElementById("modal-dots");

  var currentImageUrl = "";
  var feedPosts = [];
  var modalSlideshowUrls = [];
  var modalSlideIndex = 0;
  var modalPostIndex = -1;
  var modalSourcePost = null;
  var modalRelatedReqId = 0;
  // Modal zoom / pan state
  var modalZoom = 1;
  var modalPanX = 0;
  var modalPanY = 0;
  // Modal drag state (swipe nav + zoom pan)
  var _modalDragStartX = 0;
  var _modalDragStartY = 0;
  var _modalDragMode = null; // "pan" | "swipe" | null
  var _modalPanStartX = 0;
  var _modalPanStartY = 0;
  var currentTab = "home";
  var loginPollTimer = null;
  var splashPending = true;
  var splashStartedAt = Date.now();

  // Cycle splash label text while loading
  (function () {
    var el = document.getElementById("splash-label");
    if (!el) return;
    var msgs = ["Loading home feed", "Warming up pins", "Almost there"];
    var i = 0;
    var t = setInterval(function () {
      if (!splashPending) { clearInterval(t); return; }
      i = (i + 1) % msgs.length;
      el.style.opacity = "0";
      setTimeout(function () {
        if (!splashPending) return;
        el.textContent = msgs[i];
        el.style.opacity = "";
      }, 300);
    }, 2800);
  })();
  var homeMoreExhausted = false;
  var searchMoreExhausted = false;
  var loadingMoreGrid = false;
  var lastSearchQuery = "";
  var feedEpoch = 0;       // incremented on every new feed load; stale callbacks check this
  var bgLoading = false;   // true while background home-feed loading is active
  var likedKeys = new Set();
  var collectionsCache = [];
  var currentCollectionId = null;
  var selectMode = false;
  var selectedKeys = new Set();
  var searchHistory = [];
  var colDialogPost = null;
  var SEARCH_HISTORY_KEY = "JAPW_search_history";
  var seenPostKeys = new Set();
  var hadSession = false;   // true once home feed loads successfully at least once
  var homeSavedPosts = [];
  var homeSavedExhausted = false;
  var homeSavedKeys = new Set();
  var homeEpoch = 0;
  var xArtists = [];              // list of { username, display_name, avatar_url }
  var xPostsByArtist = {};        // username → posts[]
  var xActiveArtist = null;       // null = all artists
  var xPanelOpen = false;
  var xRefreshPollTimer = null;   // setInterval handle while background refresh is active
  var xAllPosts = [];             // full mixed post list for the current view
  var xPostsOffset = 0;          // how many have been rendered so far
  var X_PAGE_SIZE = 40;          // posts rendered per page
  var homeLoadingMore = false;
  /** Chain extra /home/more requests while the grid is still shallow so the next batch is already in flight. */
  var homeAutoPrefetchChains = 0;
  var searchAutoPrefetchChains = 0;
  var HOME_AUTO_PREFETCH_UNTIL_POSTS = 120;
  var AUTO_PREFETCH_MAX_CHAINS = 24;
  var scrollPrefetchRaf = null;
  var infiniteScrollObs = null;
  var infiniteObsResizeTimer = null;
  var lazyImageObserver = null;

  /** How far above the bottom we start loading the next batch (viewport-aware so tall screens prefetch earlier). */
  function scrollPrefetchThresholdPx() {
    var vh = window.innerHeight || 900;
    return Math.max(8800, Math.round(vh * 3.15));
  }

  /** IntersectionObserver rootMargin bottom (px): trigger before the sentinel enters view. */
  function infiniteObserverRootMargin() {
    var vh = window.innerHeight || 900;
    var px = Math.max(6800, Math.round(vh * 2.85));
    return "0px 0px " + px + "px 0px";
  }

  function setupLazyImageObserver() {
    if (typeof IntersectionObserver === "undefined") return;
    if (lazyImageObserver) { try { lazyImageObserver.disconnect(); } catch (e) {} }
    lazyImageObserver = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (!entries[i].isIntersecting) continue;
        var el = entries[i].target;
        var img = el.querySelector("img[data-lazy-src]");
        if (img) {
          img.src = img.getAttribute("data-lazy-src");
          img.removeAttribute("data-lazy-src");
        }
        lazyImageObserver.unobserve(el);
      }
    }, { rootMargin: "0px 0px 3000px 0px" });
  }

  function rafTwice(fn) {
    requestAnimationFrame(function () {
      requestAnimationFrame(fn);
    });
  }

  /** If the document is still "short", queue another page so users rarely scroll into an empty gap. */
  function ensureInfiniteFeedBuffer() {
    var vh = window.innerHeight || 900;
    var docEl = document.documentElement;
    var body = document.body;
    var total = Math.max(body.scrollHeight, docEl.scrollHeight, 0);
    if (total >= vh * 2.65) return;
    if (currentTab === "home") {
      if (homeMoreExhausted || homeLoadingMore || feedPosts.length < 1) return;
      loadMoreHome();
    } else if (currentTab === "search") {
      if (searchMoreExhausted || loadingMoreGrid || feedPosts.length < 1 || !lastSearchQuery) return;
      loadMoreSearch();
    } else if (currentTab === "artists") {
      if (xPostsOffset < xAllPosts.length) loadMoreX();
    }
  }
  var resFilter = { enabled: false, w: 1920, h: 1080, mode: "min" };

  // ─── Helpers ───
  function createDownloadIcon() {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");

    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4");
    svg.appendChild(path);

    var polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", "7 10 12 15 17 10");
    svg.appendChild(polyline);

    var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", "12");
    line.setAttribute("y1", "15");
    line.setAttribute("x2", "12");
    line.setAttribute("y2", "3");
    svg.appendChild(line);

    return svg;
  }

  function beginSplash() {
    // Splash is fully opaque from first paint via CSS; nothing to do here.
  }

  function finishSplash() {
    if (!splashPending) return;
    splashPending = false;
    var minMs = 650;
    var elapsed = Date.now() - splashStartedAt;
    var wait = Math.max(0, minMs - elapsed);
    setTimeout(function () {
      if (splash) {
        splash.classList.add("splash-fade-out");
        splash.setAttribute("aria-hidden", "true");
        splash.setAttribute("aria-busy", "false");
      }
      document.body.classList.remove("splash-active");
      setTimeout(function () {
        if (splash) splash.classList.add("hidden");
      }, 950);
    }, wait);
  }

  function showEmpty(title, subtitle) {
    if (emptyTitleEl) emptyTitleEl.textContent = title;
    if (emptySubEl) { emptySubEl.textContent = subtitle || ""; emptySubEl.className = "subtext"; }
    var old = emptyState.querySelector(".empty-sync-btn");
    if (old) old.remove();
    emptyState.classList.remove("hidden");
    updateSentinelVisibility(false);
  }

  function showEmptyWithSync(title, subtitle) {
    showEmpty(title, subtitle);
    if (!emptyState.querySelector(".empty-sync-btn")) {
      var btn = document.createElement("button");
      btn.className = "empty-sync-btn";
      btn.textContent = "Sync now";
      btn.addEventListener("click", function () {
        btn.remove();
        if (pinterestConnectBtn) pinterestConnectBtn.click();
      });
      emptyState.appendChild(btn);
    }
  }

  function updateSentinelVisibility(show) {
    if (!infiniteSentinel) return;
    infiniteSentinel.classList.toggle("hidden", !show);
    infiniteSentinel.setAttribute("aria-hidden", show ? "false" : "true");
  }

  function setInfiniteLoading(on) {
    if (!infiniteSentinel || !infiniteHint) return;
    infiniteSentinel.classList.toggle("is-loading", on);
    infiniteHint.textContent = on ? "Loading more…" : "";
  }

  function applyAuthStatus(data) {
    var connected = data && data.connected;
    var busy = data && data.login_in_progress;
    if (authBadge) {
      if (busy) {
        authBadge.textContent = "Pinterest: syncing…";
      } else if (connected) {
        authBadge.textContent = "Pinterest: connected";
      } else {
        authBadge.textContent = "Pinterest: not connected";
      }
    }
    if (pinterestStatus) {
      pinterestStatus.className = "settings-status";
      if (busy) {
        pinterestStatus.classList.add("settings-status--busy");
        pinterestStatus.textContent = "Reading cookies from your browsers…";
      } else if (connected) {
        pinterestStatus.classList.add("settings-status--connected");
        pinterestStatus.textContent = "Connected. Home, boards, and search use your account.";
      } else {
        pinterestStatus.classList.add("settings-status--idle");
        pinterestStatus.textContent = "Not connected. Sync to load your home feed.";
      }
    }
    if (pinterestDisconnectBtn) {
      pinterestDisconnectBtn.classList.toggle("hidden", !connected || busy);
    }
    if (pinterestConnectBtn) {
      pinterestConnectBtn.disabled = !!busy;
    }
    if (pinterestOpenBrowserBtn) {
      pinterestOpenBrowserBtn.disabled = !!busy;
    }
  }

  function refreshAuthBadge() {
    fetch("/api/auth/status")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        applyAuthStatus(data);
      })
      .catch(function () {
        if (authBadge) authBadge.textContent = "Pinterest: …";
      });
  }

  function stopLoginPoll() {
    if (loginPollTimer) {
      clearInterval(loginPollTimer);
      loginPollTimer = null;
    }
  }

  function startLoginPoll() {
    stopLoginPoll();
    var n = 0;
    loginPollTimer = setInterval(function () {
      n += 1;
      if (n > 720) {
        stopLoginPoll();
        showToast("✗ Sync timed out");
        refreshAuthBadge();
        return;
      }
      fetch("/api/auth/status")
        .then(function (res) { return res.json(); })
        .then(function (data) {
          applyAuthStatus(data);
          if (!data.login_in_progress) {
            stopLoginPoll();
            if (data.last_error) {
              showToast("✗ " + data.last_error);
            } else if (data.connected) {
              showToast("✓ Pinterest connected");
              if (currentTab === "home") {
                loadHome();
              }
            }
          }
        })
        .catch(function () { /* ignore */ });
    }, 1000);
  }

  // ─── Tabs & Home ───
  function setTab(tab) {
    // Save home feed state before navigating away so we can restore it instantly
    if (currentTab === "home" && feedPosts.length > 0) {
      homeSavedPosts = feedPosts.slice();
      homeSavedKeys = new Set(seenPostKeys);
      homeSavedExhausted = homeMoreExhausted;
    }

    feedEpoch++;
    // Do NOT reset bgLoading: home background loading should continue across tab switches.
    // Stop X refresh polling when leaving the artists tab
    if (currentTab === "artists" && tab !== "artists") {
      _stopXRefreshPoll();
      _setXRefreshingIndicator(false);
    }
    currentCollectionId = null;
    currentTab = tab;

    [tabHome, tabSearch, tabLiked, tabCollections, tabArtists].forEach(function (btn) {
      if (!btn) return;
      var t = btn.getAttribute("data-tab");
      btn.classList.toggle("active", t === tab);
      btn.setAttribute("aria-pressed", String(t === tab));
    });

    var isSearch = tab === "search";
    if (searchRow) searchRow.classList.toggle("hidden", !isSearch);
    if (topbarSpacer) topbarSpacer.classList.toggle("hidden", isSearch);

    // Show home refresh button only on home tab
    if (homeRefreshBtn) {
      homeRefreshBtn.classList.toggle("hidden", tab !== "home");
      if (tab !== "home") homeRefreshBtn.classList.remove("refreshing");
    }

    var isCollectionsRoot = tab === "collections" && !currentCollectionId;
    if (collectionsView) collectionsView.classList.toggle("hidden", !isCollectionsRoot);
    gallery.classList.toggle("hidden", isCollectionsRoot);

    // Show/hide the X filter bar
    if (xFilterBar) {
      xFilterBar.classList.toggle("hidden", tab !== "artists");
      if (tab === "artists") syncFilterBarTop();
    }

    clearGallery();
    feedPosts = [];
    seenPostKeys = new Set();
    homeMoreExhausted = false;
    searchMoreExhausted = false;

    if (tab === "home") {
      lastSearchQuery = "";
      if (homeSavedPosts.length > 0) {
        // Restore the home feed instantly without a network round-trip.
        emptyState.classList.add("hidden");
        homeLoadingMore = false;
        homeMoreExhausted = homeSavedExhausted;
        renderPosts(homeSavedPosts);
        updateSentinelVisibility(!homeMoreExhausted);
        scheduleScrollPrefetchCheck();
        rafTwice(ensureInfiniteFeedBuffer);
      } else {
        loadHome(false);
      }
    } else if (tab === "search") {
      lastSearchQuery = "";
      searchMoreExhausted = false;
      showEmpty("Search Pinterest", "Type a keyword and press Enter. When connected, results match your logged-in Pinterest experience.");
    } else if (tab === "liked") {
      loadLiked();
    } else if (tab === "collections") {
      loadCollectionsGrid();
    } else if (tab === "artists") {
      xActiveArtist = null;
      loadXTab();
    }
  }

  function loadHome(forceRefresh) {
    forceRefresh = !!forceRefresh;
    homeEpoch++;
    homeAutoPrefetchChains = 0;
    homeSavedPosts = [];
    homeSavedKeys = new Set();
    homeSavedExhausted = false;
    homeMoreExhausted = false;
    homeLoadingMore = false;
    bgLoading = false;
    emptyState.classList.add("hidden");
    clearGallery();
    loading.classList.remove("hidden");
    var epoch = ++feedEpoch;

    var homeUrl = forceRefresh ? "/api/home?refresh=1" : "/api/home";
    fetch(homeUrl)
      .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
      .then(function (pair) {
        if (epoch !== feedEpoch) return;
        var res = pair.res;
        var data = pair.data;
        if (res.status === 401) {
          if (hadSession) {
            showEmptyWithSync(
              "Session expired",
              "Your Pinterest session has expired. Sync again to restore your feed."
            );
          } else {
            showEmptyWithSync(
              "Connect Pinterest",
              "Sync your browser session to load your personalized home feed. Works with Chrome, Edge, Firefox, and others."
            );
          }
          return;
        }
        if (!res.ok || data.error) {
          showEmpty("Could not load home feed", (data && data.error) || "Try again or check your connection.");
          return;
        }
        var posts = normalizePostsPayload(data);
        if (posts.length > 0) {
          hadSession = true;
          renderPosts(posts);
          homeSavedPosts = feedPosts.slice();
          homeSavedKeys = new Set(seenPostKeys);
          updateSentinelVisibility(true);
          scheduleScrollPrefetchCheck();
          bgLoading = true;
          scheduleBgLoad();
          rafTwice(ensureInfiniteFeedBuffer);
          if (feedPosts.length < HOME_AUTO_PREFETCH_UNTIL_POSTS) {
            bgLoading = true;
            setTimeout(function () { loadMoreHome(); }, 100);
          }
        } else {
          showEmpty(
            "No pins loaded",
            "Pinterest may have changed their layout, or your feed is empty. Try again in a moment."
          );
        }
      })
      .catch(function () {
        if (epoch !== feedEpoch) return;
        showEmpty("Home feed failed", "Check your connection and try again.");
      })
      .finally(function () {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        if (homeRefreshBtn) homeRefreshBtn.classList.remove("refreshing");
        finishSplash();
        scheduleScrollPrefetchCheck();
      });
  }

  if (homeRefreshBtn) {
    homeRefreshBtn.addEventListener("click", function () {
      homeRefreshBtn.classList.add("refreshing");
      showToast("Refreshing home...");
      loadHome(true);
    });
  }

  if (tabHome) {
    tabHome.addEventListener("click", function () {
      if (currentTab === "home") {
        if (homeRefreshBtn) homeRefreshBtn.classList.add("refreshing");
        showToast("Refreshing home...");
        loadHome(true);
        return;
      }
      setTab("home");
    });
  }
  if (tabSearch) {
    tabSearch.addEventListener("click", function () { setTab("search"); });
  }
  if (tabLiked) {
    tabLiked.addEventListener("click", function () { setTab("liked"); });
  }
  if (tabCollections) {
    tabCollections.addEventListener("click", function () { setTab("collections"); });
  }
  if (tabArtists) {
    tabArtists.addEventListener("click", function () {
      if (currentTab === "artists") {
        // Refresh — clear cache and re-fetch
        xPostsByArtist = {};
        loadXTab();
        return;
      }
      setTab("artists");
    });
  }

  // ─── Liked ───
  function loadLikedState() {
    fetch("/api/likes")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        likedKeys = new Set();
        (data.posts || []).forEach(function (p) {
          if (p.key) likedKeys.add(p.key);
        });
      })
      .catch(function () {});
  }

  function toggleLike(post, likeBtn, itemEl) {
    var urls = post.urls || [];
    if (!urls.length) return;
    fetch("/api/likes/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: urls })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.liked) {
          likedKeys.add(data.key);
          if (likeBtn) likeBtn.classList.add("liked");
          if (itemEl) itemEl.classList.add("is-liked");
        } else {
          likedKeys.delete(data.key);
          if (likeBtn) likeBtn.classList.remove("liked");
          if (itemEl) itemEl.classList.remove("is-liked");
          if (currentTab === "liked") {
            if (itemEl && itemEl.parentNode) itemEl.remove();
            if (gallery.querySelectorAll(".gallery-item").length === 0) {
              showEmpty("No liked posts", "Heart images to save them here.");
            }
          }
        }
      })
      .catch(function () {});
  }

  function loadLiked() {
    var epoch = ++feedEpoch;
    emptyState.classList.add("hidden");
    clearGallery();
    loading.classList.remove("hidden");
    fetch("/api/likes")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        var posts = (data.posts || []).map(function (p) { return { urls: p.urls || [] }; })
          .filter(function (p) { return p.urls.length; });
        if (posts.length > 0) {
          renderPosts(posts);
          updateSentinelVisibility(false);
        } else {
          showEmpty("No liked posts yet", "Tap the heart on any image to save it here.");
        }
      })
      .catch(function () {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        showEmpty("Could not load likes", "Try again.");
      });
  }

  // ─── Collections ───
  function loadCollectionsGrid() {
    if (collectionsView) collectionsView.classList.remove("hidden");
    gallery.classList.add("hidden");
    collectionsView.innerHTML = "";

    var toolbar = document.createElement("div");
    toolbar.className = "collections-toolbar";
    var title = document.createElement("span");
    title.className = "collections-toolbar-title";
    title.textContent = "Collections";
    var newBtn = document.createElement("button");
    newBtn.className = "collections-new-btn";
    newBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> New collection';
    newBtn.addEventListener("click", function () {
      showPromptDialog("New collection", "Collection name…", "Create").then(function (name) {
        if (!name) return;
        fetch("/api/collections", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name })
        })
          .then(function (res) { return res.json(); })
          .then(function (data) {
            if (data.collection) {
              collectionsCache.push(data.collection);
              loadCollectionsGrid();
            }
          });
      });
    });
    toolbar.appendChild(title);
    toolbar.appendChild(newBtn);
    collectionsView.appendChild(toolbar);

    fetch("/api/collections")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        collectionsCache = data.collections || [];
        if (collectionsCache.length === 0) {
          var empty = document.createElement("div");
          empty.style.cssText = "flex:0 0 100%;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:40vh;gap:14px;color:var(--text-dim);font-size:13px;";
          empty.textContent = "No collections yet. Create one to organise your liked posts.";
          collectionsView.appendChild(empty);
          return;
        }
        collectionsCache.forEach(function (col, i) {
          var card = document.createElement("div");
          card.className = "collection-card";
          card.style.animationDelay = (i * 0.04) + "s";

          if (col.cover) {
            var img = document.createElement("img");
            img.className = "collection-card-cover";
            img.src = thumbnailUrl(col.cover);
            img.alt = col.name;
            card.appendChild(img);
          } else {
            var ph = document.createElement("div");
            ph.className = "collection-card-cover-empty";
            ph.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
            card.appendChild(ph);
          }

          var info = document.createElement("div");
          info.className = "collection-card-info";
          var nameEl = document.createElement("div");
          nameEl.className = "collection-card-name";
          nameEl.textContent = col.name;
          var countEl = document.createElement("div");
          countEl.className = "collection-card-count";
          countEl.textContent = col.count + (col.count === 1 ? " post" : " posts");
          info.appendChild(nameEl);
          info.appendChild(countEl);
          card.appendChild(info);

          var delBtn = document.createElement("button");
          delBtn.className = "collection-card-del";
          delBtn.setAttribute("aria-label", "Delete collection");
          delBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
          delBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            showConfirmDialog(
              "Delete collection",
              "Delete \u201c" + col.name + "\u201d? This cannot be undone.",
              "Delete"
            ).then(function (ok) {
              if (!ok) return;
              fetch("/api/collections/" + col.id, { method: "DELETE" })
                .then(function () { loadCollectionsGrid(); });
            });
          });
          card.appendChild(delBtn);

          card.addEventListener("click", function () { openCollection(col.id, col.name); });
          collectionsView.appendChild(card);
        });
      })
      .catch(function () {
        collectionsView.innerHTML += "<div style='flex:0 0 100%;color:var(--text-dim);font-size:13px;padding:20px'>Could not load collections.</div>";
      });
  }

  function openCollection(colId, colName) {
    currentCollectionId = colId;
    collectionsView.classList.add("hidden");
    gallery.classList.remove("hidden");
    clearGallery();
    feedPosts = [];

    // Back bar
    var backBar = document.createElement("div");
    backBar.className = "collections-back-bar";
    var backBtn = document.createElement("button");
    backBtn.className = "collections-back-btn";
    backBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg> Collections';
    backBtn.addEventListener("click", function () {
      currentCollectionId = null;
      setTab("collections");
    });
    var titleEl = document.createElement("span");
    titleEl.className = "collections-back-title";
    titleEl.textContent = colName || "Collection";
    backBar.appendChild(backBtn);
    backBar.appendChild(titleEl);
    gallery.insertBefore(backBar, gallery.firstChild);

    loading.classList.remove("hidden");
    fetch("/api/collections/" + colId + "/posts")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        loading.classList.add("hidden");
        var posts = (data.posts || []).map(function (p) { return { urls: p.urls || [] }; })
          .filter(function (p) { return p.urls.length; });
        if (posts.length > 0) {
          renderPosts(posts);
          updateSentinelVisibility(false);
        } else {
          showEmpty("Empty collection", "Add posts to this collection using the folder icon on any image.");
        }
      })
      .catch(function () {
        loading.classList.add("hidden");
        showEmpty("Could not load collection", "Try again.");
      });
  }

  // ─── X / Artists ─────────────────────────────────────────────────────────────

  function syncFilterBarTop() {
    if (!xFilterBar) return;
    var topbar = document.getElementById("topbar");
    if (topbar) xFilterBar.style.top = topbar.offsetHeight + "px";
  }

  function openXPanel() {
    if (!xPanel || !xPanelBackdrop) return;
    xPanelOpen = true;
    xPanel.classList.add("open");
    xPanelBackdrop.classList.add("open");
    renderXArtistsList();
    refreshXSessionStatus();
  }

  function closeXPanel() {
    if (!xPanel || !xPanelBackdrop) return;
    xPanelOpen = false;
    xPanel.classList.remove("open");
    xPanelBackdrop.classList.remove("open");
  }

  function refreshXSessionStatus() {
    fetch("/x/auth/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var connected = !!data.connected;
        if (xSessionStatus) {
          xSessionStatus.textContent = connected ? "Connected" : "Not connected";
          xSessionStatus.className = "x-session-status" + (connected ? " connected" : "");
        }
        if (xSyncBtn) xSyncBtn.textContent = connected ? "Re-sync" : "Sync from browser";
        if (xDisconnectBtn) xDisconnectBtn.classList.toggle("hidden", !connected);
      })
      .catch(function () {});
  }

  if (xSyncBtn) {
    xSyncBtn.addEventListener("click", function () {
      xSyncBtn.disabled = true;
      xSyncBtn.textContent = "Syncing\u2026";
      fetch("/x/auth/sync", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            showToast("\u2717 " + data.error);
          } else {
            showToast("\u2713 X session synced");
            refreshXSessionStatus();
          }
        })
        .catch(function () { showToast("\u2717 Sync failed"); })
        .finally(function () {
          xSyncBtn.disabled = false;
          refreshXSessionStatus();
        });
    });
  }

  if (xDisconnectBtn) {
    xDisconnectBtn.addEventListener("click", function () {
      fetch("/x/auth/logout", { method: "POST" })
        .then(function () {
          showToast("X session cleared");
          refreshXSessionStatus();
        });
    });
  }

  function loadXTab() {
    // Load artist list, then decide whether to fetch media or show empty state
    fetch("/x/artists")
      .then(function (r) { return r.json(); })
      .then(function (artists) {
        xArtists = Array.isArray(artists) ? artists : [];
        renderXFilterPills();
        if (xArtists.length === 0) {
          showEmpty("No artists added", "Add an X/Twitter creator to start browsing their media.");
          updateSentinelVisibility(false);
          if (!emptyState.querySelector(".empty-sync-btn")) {
            var manageBtn = document.createElement("button");
            manageBtn.className = "empty-sync-btn";
            manageBtn.textContent = "Manage artists";
            manageBtn.addEventListener("click", function () { openXPanel(); });
            emptyState.appendChild(manageBtn);
          }
        } else {
          loadXMedia(false);
        }
      })
      .catch(function () {
        xArtists = [];
        showEmpty("Could not load artists", "Try again.");
      });
  }

  function _stopXRefreshPoll() {
    if (xRefreshPollTimer !== null) {
      clearInterval(xRefreshPollTimer);
      xRefreshPollTimer = null;
    }
  }

  function _setXRefreshingIndicator(on, usernames) {
    if (xRefreshBtn) {
      if (on) {
        xRefreshBtn.disabled = true;
        xRefreshBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1s linear infinite"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-1.64-8.36L23 10"/></svg> Fetching';
      } else {
        xRefreshBtn.disabled = false;
        xRefreshBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-1.64-8.36L23 10"/></svg> Refresh';
      }
    }
    if (xFetchBanner) {
      if (on) {
        xFetchBanner.classList.remove("hidden");
        if (xFetchLabel) {
          var names = (usernames && usernames.length)
            ? usernames.map(function (u) { return "@" + u; }).join(", ")
            : "";
          xFetchLabel.textContent = names
            ? "Fetching media for " + names + "\u2026"
            : "Fetching media\u2026";
        }
      } else {
        xFetchBanner.classList.add("hidden");
      }
    }
  }

  function loadXMedia(forceRefresh) {
    var epoch = ++feedEpoch;
    _stopXRefreshPoll();
    emptyState.classList.add("hidden");
    clearGallery();
    feedPosts = [];
    seenPostKeys = new Set();
    loading.classList.remove("hidden");

    var url = "/x/media";
    if (forceRefresh) url += "?refresh=1";
    if (xActiveArtist) url += (forceRefresh ? "&" : "?") + "username=" + encodeURIComponent(xActiveArtist);

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");

        var posts = (data.posts || []).filter(function (p) { return p && p.urls && p.urls.length; });

        // Cache by artist
        posts.forEach(function (p) {
          var a = (p.artist || "").toLowerCase();
          if (!xPostsByArtist[a]) xPostsByArtist[a] = [];
          var key = p.pin_url || (p.urls && p.urls[0]) || "";
          var dup = xPostsByArtist[a].some(function (e) {
            return (e.pin_url || (e.urls && e.urls[0]) || "") === key;
          });
          if (!dup) xPostsByArtist[a].push(p);
        });

        if (posts.length > 0) {
          renderXPosts();
        } else if (!data.refreshing) {
          if (data.has_session === false) {
            showEmpty("Connect X / Twitter", "Sync your X session to browse artist media. Close your browser first if the cookie file is locked.");
            if (!emptyState.querySelector(".empty-sync-btn")) {
              var xSyncEmptyBtn = document.createElement("button");
              xSyncEmptyBtn.className = "empty-sync-btn";
              xSyncEmptyBtn.textContent = "Sync X session";
              xSyncEmptyBtn.addEventListener("click", function () {
                xSyncEmptyBtn.disabled = true;
                xSyncEmptyBtn.textContent = "Syncing\u2026";
                fetch("/x/auth/sync", { method: "POST" })
                  .then(function (r) { return r.json(); })
                  .then(function (data) {
                    if (data.error) {
                      showToast("\u2717 " + data.error);
                      xSyncEmptyBtn.disabled = false;
                      xSyncEmptyBtn.textContent = "Sync X session";
                    } else {
                      showToast("\u2713 X session synced");
                      refreshXSessionStatus();
                      loadXTab();
                    }
                  })
                  .catch(function () {
                    showToast("\u2717 Sync failed");
                    xSyncEmptyBtn.disabled = false;
                    xSyncEmptyBtn.textContent = "Sync X session";
                  });
              });
              emptyState.appendChild(xSyncEmptyBtn);
            }
          } else {
            showEmpty("No posts found", "No images found. The account may be private or have no media.");
          }
        }

        // If backend is scraping in background, poll until done then refresh display
        if (data.refreshing) {
          _setXRefreshingIndicator(true, data.refreshing_usernames || []);
          xRefreshPollTimer = setInterval(function () {
            if (currentTab !== "artists") { _stopXRefreshPoll(); _setXRefreshingIndicator(false); return; }
            fetch("/x/media/refresh-status")
              .then(function (r) { return r.json(); })
              .then(function (s) {
                if (!s.refreshing) {
                  _stopXRefreshPoll();
                  _setXRefreshingIndicator(false);
                  xPostsByArtist = {};
                  loadXMedia(false);
                } else {
                  _setXRefreshingIndicator(true, s.usernames || []);
                }
              })
              .catch(function () { _stopXRefreshPoll(); _setXRefreshingIndicator(false); });
          }, 2000);
        } else {
          _setXRefreshingIndicator(false);
        }
      })
      .catch(function () {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        showEmpty("Could not fetch posts", "Check your connection and try again.");
      });
  }

  function _buildXPostList() {
    if (xActiveArtist) {
      return (xPostsByArtist[xActiveArtist.toLowerCase()] || []).slice();
    }
    // Round-robin interleave so artists are mixed evenly
    var queues = xArtists
      .map(function (a) { return (xPostsByArtist[a.username.toLowerCase()] || []).slice(); })
      .filter(function (q) { return q.length > 0; });
    var posts = [];
    while (queues.length > 0) {
      for (var qi = queues.length - 1; qi >= 0; qi--) {
        posts.push(queues[qi].shift());
        if (queues[qi].length === 0) queues.splice(qi, 1);
      }
    }
    return posts;
  }

  function renderXPosts() {
    clearGallery();
    feedPosts = [];
    seenPostKeys = new Set();
    xAllPosts = _buildXPostList();
    xPostsOffset = 0;

    if (xAllPosts.length === 0) {
      if (xArtists.length === 0) {
        showEmpty("No artists added", "Add an X/Twitter creator to start browsing their media.");
        if (!emptyState.querySelector(".empty-sync-btn")) {
          var manageBtn2 = document.createElement("button");
          manageBtn2.className = "empty-sync-btn";
          manageBtn2.textContent = "Manage artists";
          manageBtn2.addEventListener("click", function () { openXPanel(); });
          emptyState.appendChild(manageBtn2);
        }
      } else {
        showEmpty("No posts cached", "Switch artist or refresh.");
      }
      updateSentinelVisibility(false);
      return;
    }

    var firstPage = xAllPosts.slice(0, X_PAGE_SIZE);
    xPostsOffset = firstPage.length;
    renderPosts(firstPage);
    updateSentinelVisibility(xPostsOffset < xAllPosts.length);
  }

  function loadMoreX() {
    if (xPostsOffset >= xAllPosts.length) {
      updateSentinelVisibility(false);
      return;
    }
    var next = xAllPosts.slice(xPostsOffset, xPostsOffset + X_PAGE_SIZE);
    xPostsOffset += next.length;
    appendPosts(next);
    updateSentinelVisibility(xPostsOffset < xAllPosts.length);
  }

  function setXFilter(username) {
    xActiveArtist = username;
    renderXFilterPills();
    var cached = username
      ? (xPostsByArtist[username.toLowerCase()] || []).length > 0
      : xArtists.some(function (a) { return (xPostsByArtist[a.username.toLowerCase()] || []).length > 0; });
    if (cached) {
      renderXPosts();
    } else {
      loadXMedia();
    }
  }

  function renderXFilterPills() {
    if (!xFilterPills) return;
    xFilterPills.innerHTML = "";

    var allPill = document.createElement("button");
    allPill.type = "button";
    allPill.className = "x-filter-pill" + (xActiveArtist === null ? " active" : "");
    allPill.textContent = "All";
    allPill.addEventListener("click", function () { setXFilter(null); });
    xFilterPills.appendChild(allPill);

    xArtists.forEach(function (a) {
      var pill = document.createElement("button");
      pill.type = "button";
      pill.className = "x-filter-pill" + (xActiveArtist === a.username ? " active" : "");
      pill.textContent = "@" + a.username;
      pill.addEventListener("click", function () { setXFilter(a.username); });
      xFilterPills.appendChild(pill);
    });
  }

  function renderXArtistsList() {
    if (!xArtistsList) return;
    xArtistsList.innerHTML = "";
    if (xArtists.length === 0) {
      var empty = document.createElement("p");
      empty.className = "x-artists-empty";
      empty.textContent = "No artists added yet.";
      xArtistsList.appendChild(empty);
      return;
    }
    xArtists.forEach(function (a) {
      xArtistsList.appendChild(createXArtistRow(a));
    });
  }

  function createXArtistRow(artist) {
    var row = document.createElement("div");
    row.className = "x-artist-row";
    row.setAttribute("data-username", artist.username);

    var avatar = document.createElement("div");
    avatar.className = "x-artist-avatar";
    if (artist.avatar_url) {
      var img = document.createElement("img");
      img.src = artist.avatar_url;
      img.alt = artist.username;
      img.onerror = function () {
        img.remove();
        avatar.textContent = (artist.username[0] || "?").toUpperCase();
      };
      avatar.appendChild(img);
    } else {
      avatar.textContent = (artist.username[0] || "?").toUpperCase();
    }

    var info = document.createElement("div");
    info.className = "x-artist-info";

    var nameEl = document.createElement("div");
    nameEl.className = "x-artist-name";
    nameEl.textContent = artist.display_name || artist.username;

    var handleEl = document.createElement("div");
    handleEl.className = "x-artist-handle";
    handleEl.textContent = "@" + artist.username;

    info.appendChild(nameEl);
    info.appendChild(handleEl);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "x-artist-remove-btn";
    removeBtn.setAttribute("aria-label", "Remove @" + artist.username);
    removeBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>';
    removeBtn.addEventListener("click", function () {
      showConfirmDialog(
        "Remove artist",
        "Remove @" + artist.username + " from your artists list?",
        "Remove"
      ).then(function (ok) { if (ok) removeXArtist(artist.username); });
    });

    row.appendChild(avatar);
    row.appendChild(info);
    row.appendChild(removeBtn);
    return row;
  }

  function addXArtist(username) {
    username = username.trim().replace(/^@/, "");
    if (!username) return;

    xAddBtn.disabled = true;
    xAddBtn.textContent = "Adding\u2026";

    fetch("/x/artists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; }); })
      .then(function (p) {
        if (p.status === 409) {
          showToast("@" + username + " is already in your list");
          return;
        }
        if (!p.ok) {
          showToast("\u2717 " + ((p.data && p.data.error) || "Could not add artist"));
          return;
        }
        var artist = p.data;
        xArtists.push(artist);
        xAddInput.value = "";
        renderXArtistsList();
        renderXFilterPills();
        showToast("Added @" + artist.username);
        // Poll for enriched info (background thread on server)
        setTimeout(function () { refreshXArtistInfo(artist.username); }, 4000);
      })
      .catch(function () { showToast("\u2717 Could not add artist"); })
      .finally(function () {
        xAddBtn.disabled = false;
        xAddBtn.textContent = "Add";
      });
  }

  function refreshXArtistInfo(username) {
    fetch("/x/artists/" + encodeURIComponent(username) + "/info")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        for (var i = 0; i < xArtists.length; i++) {
          if (xArtists[i].username.toLowerCase() === username.toLowerCase()) {
            xArtists[i].display_name = data.display_name || xArtists[i].display_name;
            xArtists[i].avatar_url = data.avatar_url || xArtists[i].avatar_url;
            break;
          }
        }
        // Update the row in the panel if it's open
        var row = xArtistsList && xArtistsList.querySelector('[data-username="' + username + '"]');
        if (row) {
          var updated = xArtists.find(function (a) { return a.username === username; });
          if (updated) {
            var newRow = createXArtistRow(updated);
            row.parentNode.replaceChild(newRow, row);
          }
        }
        renderXFilterPills();
      })
      .catch(function () {});
  }

  function removeXArtist(username) {
    fetch("/x/artists/" + encodeURIComponent(username), { method: "DELETE" })
      .then(function () {
        xArtists = xArtists.filter(function (a) { return a.username !== username; });
        delete xPostsByArtist[username.toLowerCase()];
        if (xActiveArtist === username) xActiveArtist = null;
        renderXArtistsList();
        renderXFilterPills();
        if (currentTab === "artists") renderXPosts();
        showToast("Removed @" + username);
      })
      .catch(function () { showToast("\u2717 Could not remove artist"); });
  }

  if (xManageBtn) {
    xManageBtn.addEventListener("click", openXPanel);
  }
  if (xRefreshBtn) {
    xRefreshBtn.addEventListener("click", function () {
      if (currentTab !== "artists") return;
      showToast("Refreshing artist media\u2026");
      xPostsByArtist = {};
      loadXMedia(true);
    });
  }
  if (xPanelClose) {
    xPanelClose.addEventListener("click", closeXPanel);
  }
  if (xPanelBackdrop) {
    xPanelBackdrop.addEventListener("click", closeXPanel);
  }
  if (xAddBtn) {
    xAddBtn.addEventListener("click", function () {
      addXArtist(xAddInput ? xAddInput.value : "");
    });
  }
  if (xAddInput) {
    xAddInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") addXArtist(xAddInput.value);
    });
  }

  // ─── End X / Artists ─────────────────────────────────────────────────────────

  function showAddToCollectionDialog(post) {
    colDialogPost = post;
    colDialog.classList.remove("hidden");
    colDialogInput.value = "";
    renderColDialogList();
  }

  function closeColDialog() {
    colDialog.classList.add("hidden");
    colDialogPost = null;
  }

  // ─── Confirm dialog ───
  var _confirmResolve = null;
  var confirmDialog = document.getElementById("confirm-dialog");
  var confirmDialogTitle = document.getElementById("confirm-dialog-title");
  var confirmDialogMessage = document.getElementById("confirm-dialog-message");
  var confirmDialogConfirmBtn = document.getElementById("confirm-dialog-confirm");
  var confirmDialogCancelBtn = document.getElementById("confirm-dialog-cancel");

  function showConfirmDialog(title, message, confirmLabel) {
    return new Promise(function (resolve) {
      _confirmResolve = resolve;
      confirmDialogTitle.textContent = title || "Are you sure?";
      confirmDialogMessage.textContent = message || "";
      confirmDialogConfirmBtn.textContent = confirmLabel || "Remove";
      confirmDialog.classList.remove("hidden");
    });
  }

  function _closeConfirmDialog(result) {
    confirmDialog.classList.add("hidden");
    if (_confirmResolve) { _confirmResolve(result); _confirmResolve = null; }
  }

  if (confirmDialogConfirmBtn) confirmDialogConfirmBtn.addEventListener("click", function () { _closeConfirmDialog(true); });
  if (confirmDialogCancelBtn) confirmDialogCancelBtn.addEventListener("click", function () { _closeConfirmDialog(false); });
  if (confirmDialog) {
    confirmDialog.querySelector(".prompt-dialog-backdrop").addEventListener("click", function () { _closeConfirmDialog(false); });
  }

  // ─── Prompt dialog ───
  var _promptResolve = null;

  function showPromptDialog(title, placeholder, confirmLabel) {
    return new Promise(function (resolve) {
      _promptResolve = resolve;
      promptDialogTitle.textContent = title || "Enter name";
      promptDialogInput.placeholder = placeholder || "";
      promptDialogInput.value = "";
      if (confirmLabel) promptDialogConfirm.textContent = confirmLabel;
      promptDialog.classList.remove("hidden");
      requestAnimationFrame(function () { promptDialogInput.focus(); });
    });
  }

  function _closePromptDialog(value) {
    promptDialog.classList.add("hidden");
    promptDialogInput.value = "";
    if (_promptResolve) { _promptResolve(value || null); _promptResolve = null; }
  }

  promptDialogConfirm.addEventListener("click", function () {
    var val = promptDialogInput.value.trim();
    _closePromptDialog(val || null);
  });
  promptDialogCancel.addEventListener("click", function () { _closePromptDialog(null); });
  promptDialogClose.addEventListener("click", function () { _closePromptDialog(null); });
  promptDialog.querySelector(".prompt-dialog-backdrop").addEventListener("click", function () { _closePromptDialog(null); });
  promptDialogInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { var val = promptDialogInput.value.trim(); _closePromptDialog(val || null); }
    if (e.key === "Escape") { _closePromptDialog(null); }
  });

  function renderColDialogList() {
    colDialogList.innerHTML = "";
    fetch("/api/collections")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var cols = data.collections || [];
        if (cols.length === 0) {
          var empty = document.createElement("div");
          empty.className = "col-dialog-empty";
          empty.textContent = "No collections yet \u2014 create one below.";
          colDialogList.appendChild(empty);
          return;
        }
        cols.forEach(function (col) {
          var item = document.createElement("div");
          item.className = "col-dialog-item";
          var nameEl = document.createElement("span");
          nameEl.className = "col-dialog-item-name";
          nameEl.textContent = col.name;
          var countEl = document.createElement("span");
          countEl.className = "col-dialog-item-count";
          countEl.textContent = col.count + " posts";
          item.appendChild(nameEl);
          item.appendChild(countEl);
          item.addEventListener("click", function () {
            if (!colDialogPost) return;
            fetch("/api/collections/" + col.id + "/posts", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ urls: colDialogPost.urls })
            })
              .then(function () {
                showToast("\u2713 Added to \u201c" + col.name + "\u201d");
                closeColDialog();
              });
          });
          colDialogList.appendChild(item);
        });
      });
  }

  if (colDialogClose) colDialogClose.addEventListener("click", closeColDialog);
  if (colDialog) {
    colDialog.querySelector(".col-dialog-backdrop").addEventListener("click", closeColDialog);
  }
  if (colDialogCreateBtn) {
    colDialogCreateBtn.addEventListener("click", function () {
      var name = (colDialogInput.value || "").trim();
      if (!name) { colDialogInput.focus(); return; }
      fetch("/api/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.collection && colDialogPost) {
            return fetch("/api/collections/" + data.collection.id + "/posts", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ urls: colDialogPost.urls })
            }).then(function () {
              showToast("\u2713 Added to \u201c" + name + "\u201d");
              closeColDialog();
            });
          }
        });
    });
    colDialogInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") colDialogCreateBtn.click();
    });
  }

  // ─── Search history ───
  function loadSearchHistory() {
    try {
      var raw = localStorage.getItem(SEARCH_HISTORY_KEY);
      searchHistory = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(searchHistory)) searchHistory = [];
    } catch (e) { searchHistory = []; }
  }

  function saveSearchHistory(query) {
    loadSearchHistory();
    searchHistory = searchHistory.filter(function (q) { return q !== query; });
    searchHistory.unshift(query);
    if (searchHistory.length > 10) searchHistory.length = 10;
    try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory)); } catch (e) {}
  }

  function showSearchHistory() {
    loadSearchHistory();
    if (!searchHistoryDropdown || searchHistory.length === 0) return;
    searchHistoryDropdown.innerHTML = "";
    searchHistory.forEach(function (q) {
      var item = document.createElement("div");
      item.className = "search-history-item";
      item.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
      var text = document.createElement("span");
      text.className = "search-history-item-text";
      text.textContent = q;
      var clearBtn = document.createElement("button");
      clearBtn.className = "search-history-clear";
      clearBtn.textContent = "\xd7";
      clearBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        searchHistory = searchHistory.filter(function (h) { return h !== q; });
        try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory)); } catch (e2) {}
        item.remove();
        if (searchHistoryDropdown.children.length === 0) searchHistoryDropdown.classList.add("hidden");
      });
      item.appendChild(text);
      item.appendChild(clearBtn);
      item.addEventListener("click", function () {
        searchInput.value = q;
        searchHistoryDropdown.classList.add("hidden");
        doSearch();
      });
      searchHistoryDropdown.appendChild(item);
    });
    searchHistoryDropdown.classList.remove("hidden");
  }

  function hideSearchHistory() {
    if (searchHistoryDropdown) searchHistoryDropdown.classList.add("hidden");
  }

  if (searchInput) {
    searchInput.addEventListener("focus", showSearchHistory);
    searchInput.addEventListener("blur", function () {
      setTimeout(hideSearchHistory, 200);
    });
  }

  // ─── Bulk select ───
  function updateBulkBar() {
    if (!bulkBar) return;
    var n = selectedKeys.size;
    if (bulkCountLabel) bulkCountLabel.textContent = n + (n === 1 ? " selected" : " selected");
    if (n > 0 && selectMode) {
      bulkBar.classList.remove("hidden");
      requestAnimationFrame(function () { bulkBar.classList.add("visible"); });
    } else {
      bulkBar.classList.remove("visible");
      setTimeout(function () { if (!bulkBar.classList.contains("visible")) bulkBar.classList.add("hidden"); }, 350);
    }
  }

  function toggleSelectMode() {
    selectMode = !selectMode;
    if (bulkToggleBtn) bulkToggleBtn.classList.toggle("active", selectMode);
    gallery.classList.toggle("select-mode", selectMode);
    if (!selectMode) {
      selectedKeys.clear();
      gallery.querySelectorAll(".gallery-item.is-selected").forEach(function (el) { el.classList.remove("is-selected"); });
    }
    updateBulkBar();
  }

  function togglePostSelect(key, itemEl) {
    if (selectedKeys.has(key)) {
      selectedKeys.delete(key);
      if (itemEl) itemEl.classList.remove("is-selected");
    } else {
      selectedKeys.add(key);
      if (itemEl) itemEl.classList.add("is-selected");
    }
    updateBulkBar();
  }

  if (bulkToggleBtn) bulkToggleBtn.addEventListener("click", toggleSelectMode);

  if (bulkClearBtn) {
    bulkClearBtn.addEventListener("click", function () {
      selectedKeys.clear();
      gallery.querySelectorAll(".gallery-item.is-selected").forEach(function (el) { el.classList.remove("is-selected"); });
      updateBulkBar();
    });
  }

  if (bulkDownloadBtn) {
    bulkDownloadBtn.addEventListener("click", function () {
      if (selectedKeys.size === 0) return;
      var keys = Array.from(selectedKeys);
      var urls = [];
      feedPosts.forEach(function (p) {
        var k = canonicalKeyFromPinimgUrl((p.urls || [])[0] || "");
        if (keys.indexOf(k) !== -1 && p.urls[0]) urls.push(p.urls[0]);
      });
      if (urls.length === 0) { showToast("\u2717 No images to download"); return; }
      showToast("Downloading " + urls.length + " images\u2026");
      var ok = 0, fail = 0, i = 0;
      function step() {
        if (i >= urls.length) {
          var parts = [];
          if (ok) parts.push(ok + " saved");
          if (fail) parts.push(fail + " failed");
          showToast(parts.length ? "\u2713 " + parts.join(", ") : "\u2717 Download failed");
          return;
        }
        fetch("/api/download", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: urls[i++] }) })
          .then(function (r) { return r.json(); })
          .then(function (d) { if (d.success) ok++; else fail++; })
          .catch(function () { fail++; })
          .finally(step);
      }
      step();
    });
  }

  // ─── Open in browser ───
  function openInBrowser(url) {
    fetch("/api/open-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url })
    }).catch(function () {});
  }

  // ─── Search ───
  function doSearch() {
    if (currentTab !== "search") return;
    var query = searchInput.value.trim();
    if (!query) return;

    lastSearchQuery = query;
    searchMoreExhausted = false;
    searchAutoPrefetchChains = 0;
    emptyState.classList.add("hidden");
    clearGallery();
    loading.classList.remove("hidden");
    var epoch = ++feedEpoch;

    saveSearchHistory(query);
    fetch("/api/search?q=" + encodeURIComponent(query))
      .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
      .then(function (pair) {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        var res = pair.res;
        var data = pair.data;
        if (!res.ok && data.error) {
          showEmpty("Search failed", data.error);
          return;
        }
        if (data.error) {
          showEmpty("Search failed", data.error);
          return;
        }
        var posts = normalizePostsPayload(data);
        if (posts.length > 0) {
          renderPosts(posts);
          searchMoreExhausted = data.source !== "session";
          updateSentinelVisibility(true);
          scheduleScrollPrefetchCheck();
          rafTwice(ensureInfiniteFeedBuffer);
          if (data.source === "session" && !searchMoreExhausted && feedPosts.length < HOME_AUTO_PREFETCH_UNTIL_POSTS) {
            setTimeout(function () { loadMoreSearch(); }, 100);
          }
        } else {
          showEmpty("No results found", "Try a different search term");
        }
      })
      .catch(function () {
        if (epoch !== feedEpoch) return;
        loading.classList.add("hidden");
        showEmpty("Search failed", "Check your connection and try again");
      });
  }

  searchBtn.addEventListener("click", doSearch);
  searchInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") doSearch();
  });

  // ─── Gallery ───
  var galleryCols = [];
  var colCount = Math.max(2, Math.min(8, parseInt(localStorage.getItem("gridZoom") || "4", 10) || 4));

  function updateGridZoomBtnStates() {
    if (gridZoomOut) gridZoomOut.disabled = colCount >= 8;
    if (gridZoomIn) gridZoomIn.disabled = colCount <= 2;
    if (gridZoomOut) gridZoomOut.style.opacity = colCount >= 8 ? "0.35" : "";
    if (gridZoomIn) gridZoomIn.style.opacity = colCount <= 2 ? "0.35" : "";
  }

  function setColCount(n) {
    colCount = Math.max(2, Math.min(8, n));
    localStorage.setItem("gridZoom", String(colCount));
    updateGridZoomBtnStates();
    // Re-render current feed with new column count
    var posts = feedPosts.slice();
    if (posts.length > 0) {
      renderPosts(posts);
    }
  }

  if (gridZoomOut) {
    gridZoomOut.addEventListener("click", function () { setColCount(colCount + 1); });
  }
  if (gridZoomIn) {
    gridZoomIn.addEventListener("click", function () { setColCount(colCount - 1); });
  }
  updateGridZoomBtnStates();
  // Apply density class for initial colCount (in case user saved a high count)
  if (colCount >= 6) gallery.classList.add("cols-" + colCount);

  function normalizePostsPayload(data) {
    if (!data) return [];
    if (data.posts && data.posts.length) {
      return data.posts.filter(function (p) {
        return p && p.urls && p.urls.length;
      });
    }
    if (data.images && data.images.length) {
      return data.images.map(function (u) {
        return { urls: [u] };
      });
    }
    return [];
  }

  function flattenSeenUrls() {
    var out = [];
    feedPosts.forEach(function (p) {
      (p.urls || []).forEach(function (u) {
        out.push(u);
      });
    });
    return out;
  }

  /** Match pinterest_session._pinimg_canonical_key for the cover URL (dedupe posts). */
  function canonicalKeyFromPinimgUrl(url) {
    try {
      var u = String(url || "").split("?")[0].trim().toLowerCase();
      if (u.indexOf("i.pinimg.com") === -1) {
        var d = u.lastIndexOf(".");
        return d === -1 ? u : u.slice(0, d);
      }
      var m = u.match(/^https?:\/\/i\.pinimg\.com\/[^/]+\/(.+)$/i);
      if (!m) return u;
      var path = m[1];
      var dot = path.lastIndexOf(".");
      if (dot !== -1) path = path.slice(0, dot);
      return path;
    } catch (e) {
      return String(url || "");
    }
  }

  function thumbnailUrl(url) {
    // Use smaller thumbnails when cards are rendered small (many columns).
    // 236x loads ~2× faster than 474x and is plenty for small cards.
    var bucket = colCount >= 5 ? "236x" : "474x";
    return (url || "").replace(
      /i\.pinimg\.com\/(?:originals|\d+x(?:\d+)?)\//i,
      "i.pinimg.com/" + bucket + "/"
    );
  }

  function estimateSizeFromUrl(url) {
    // Returns a {w, h} estimate from the CDN path so the resolution filter can
    // work without loading the full-res image. originals → treated as very large.
    // 736px is Pinterest's max standard CDN width; images at that size or above
    // may have much larger originals — return null (unknown) so they aren't
    // filtered out. Only CDN thumbnails clearly smaller than the target are excluded.
    var u = (url || "").toLowerCase();
    if (u.indexOf("/originals/") !== -1) return { w: 9999, h: 9999 };
    var m = u.match(/pinimg\.com\/(\d+)x(?:(\d+))?\//) ;
    if (!m) return null;
    var w = parseInt(m[1], 10);
    // Can't infer original resolution from CDN width ≥ 736 — pass it through.
    if (w >= 736) return null;
    var h = m[2] ? parseInt(m[2], 10) : Math.round(w * 1.33);
    return { w: w, h: h };
  }

  function formatPinimgUrlHints(url) {
    var u = String(url || "").toLowerCase();
    var parts = [];
    var m = u.match(/pinimg\.com\/(\d+)x(?:\d+)?\//);
    if (m) parts.push("CDN " + m[1] + "px");
    else if (u.indexOf("/originals/") !== -1) parts.push("originals");
    if (u.indexOf(".webp") !== -1) parts.push("WebP");
    else if (u.indexOf(".gif") !== -1) parts.push("GIF");
    else if (u.indexOf(".png") !== -1) parts.push("PNG");
    else if (u.indexOf(".jpg") !== -1 || u.indexOf(".jpeg") !== -1) parts.push("JPEG");
    return parts.join(" · ");
  }

  function applyResolutionConfigFromApi(data) {
    if (!data) return;
    resFilter.enabled = !!data.resolution_filter_enabled;
    resFilter.w = Math.max(1, parseInt(data.resolution_target_width, 10) || 1920);
    resFilter.h = Math.max(1, parseInt(data.resolution_target_height, 10) || 1080);
    resFilter.mode = data.resolution_match_mode === "exact" ? "exact" : "min";
  }

  function passesResolutionFilter(w, h) {
    if (!resFilter.enabled) return true;
    if (!w || !h) return true;
    var tw = resFilter.w;
    var th = resFilter.h;
    if (resFilter.mode === "exact") {
      var tol = Math.max(8, Math.round(Math.max(tw, th) * 0.02));
      return Math.abs(w - tw) <= tol && Math.abs(h - th) <= tol;
    }
    return w >= tw && h >= th;
  }

  function removeFilteredPost(item, postKey) {
    if (postKey) seenPostKeys.delete(postKey);
    for (var i = feedPosts.length - 1; i >= 0; i--) {
      var u = feedPosts[i].urls && feedPosts[i].urls[0];
      if (u && canonicalKeyFromPinimgUrl(u) === postKey) {
        feedPosts.splice(i, 1);
        break;
      }
    }
    if (item.parentNode) item.remove();
    scheduleScrollPrefetchCheck();
  }

  function reapplyResolutionFilter() {
    if (!resFilter.enabled) return;
    var items = gallery.querySelectorAll(".gallery-item");
    items.forEach(function (item) {
      var key = item.getAttribute("data-post-key");
      var img = item.querySelector("img");
      if (!img) return;
      var origUrl = img.getAttribute("data-orig-url") || img.src;
      var est = estimateSizeFromUrl(origUrl);
      if (est && !passesResolutionFilter(est.w, est.h)) removeFilteredPost(item, key);
    });
  }

  function scheduleBgLoad() {
    if (!bgLoading || homeMoreExhausted || homeSavedPosts.length >= 400) {
      bgLoading = false;
      return;
    }
    setTimeout(function () {
      if (!bgLoading || homeMoreExhausted) { bgLoading = false; return; }
      loadMoreHome();
    }, 150);
  }

  /** Queue another home/more while the feed is still short (runs after .finally clears homeLoadingMore). */
  function scheduleHomeDeepPrefetch(hasMore) {
    if (hasMore === false) return;
    setTimeout(function () {
      if (currentTab !== "home" || homeMoreExhausted || homeLoadingMore) return;
      if (feedPosts.length >= HOME_AUTO_PREFETCH_UNTIL_POSTS) return;
      if (homeAutoPrefetchChains >= AUTO_PREFETCH_MAX_CHAINS) return;
      if (homeSavedPosts.length >= 400) return;
      homeAutoPrefetchChains++;
      bgLoading = true;
      loadMoreHome();
    }, 150);
  }

  function scheduleSearchDeepPrefetch(hasMore) {
    if (!hasMore) return;
    setTimeout(function () {
      if (currentTab !== "search" || searchMoreExhausted || loadingMoreGrid || !lastSearchQuery) return;
      if (feedPosts.length >= HOME_AUTO_PREFETCH_UNTIL_POSTS) return;
      if (searchAutoPrefetchChains >= AUTO_PREFETCH_MAX_CHAINS) return;
      searchAutoPrefetchChains++;
      loadMoreSearch();
    }, 150);
  }

  function scheduleScrollPrefetchCheck() {
    if (scrollPrefetchRaf !== null) return;
    scrollPrefetchRaf = requestAnimationFrame(function () {
      scrollPrefetchRaf = null;
      var docEl = document.documentElement;
      var body = document.body;
      var scrollTop = window.scrollY || docEl.scrollTop || body.scrollTop;
      var vh = window.innerHeight;
      var total = Math.max(body.scrollHeight, docEl.scrollHeight, 0);
      var distToBottom = total - scrollTop - vh;
      if (distToBottom > scrollPrefetchThresholdPx()) return;
      if (currentTab === "home") loadMoreHome();
      else if (currentTab === "search") loadMoreSearch();
      else if (currentTab === "artists" && xPostsOffset < xAllPosts.length) loadMoreX();
    });
  }

  function initGalleryCols() {
    galleryCols.forEach(function (c) {
      if (c.parentNode) c.remove();
    });
    galleryCols = [];

    // Apply density class so CSS can tighten gap/padding at high col counts
    gallery.className = gallery.className.replace(/\bcols-\d+\b/g, "").trim();
    if (colCount >= 6) gallery.classList.add("cols-" + colCount);

    var sentinel = infiniteSentinel;
    for (var i = 0; i < colCount; i++) {
        var col = document.createElement("div");
        col.className = "gallery-col";
        if (sentinel && sentinel.parentNode === gallery) {
            gallery.insertBefore(col, sentinel);
        } else {
            gallery.appendChild(col);
        }
        galleryCols.push(col);
    }
  }

  function clearGallery() {
    seenPostKeys = new Set();
    xAllPosts = [];
    xPostsOffset = 0;
    gallery.querySelectorAll(".collections-back-bar").forEach(function (el) { el.remove(); });
    galleryCols.forEach(function (c) {
      if (c.parentNode) c.remove();
    });
    galleryCols = [];
    var items = gallery.querySelectorAll(".gallery-item");
    items.forEach(function (item) { item.remove(); });
  }

  function createGalleryItem(post, batchIndex, postIndex) {
    var urls = post.urls || [];
    var url = urls[0];
    if (!url) return null;

    var gifVideoUrl = post.gif_video_url || null;
    var isGif = !!gifVideoUrl || url.toLowerCase().indexOf(".gif") !== -1;
    var downloadUrl = gifVideoUrl || url;

    var postKey = canonicalKeyFromPinimgUrl(url);
    var isLiked = likedKeys.has(postKey);

    var item = document.createElement("div");
    item.className = "gallery-item" + (isLiked ? " is-liked" : "");
    item.setAttribute("data-post-key", postKey);
    item.style.animationDelay = Math.min(batchIndex * 0.04, 0.2) + "s";

    // Select check (bulk select mode)
    var selCheck = document.createElement("div");
    selCheck.className = "select-check";
    selCheck.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    item.appendChild(selCheck);

    // Like button (top-right, outside overlay)
    var likeBtn = document.createElement("button");
    likeBtn.className = "like-btn" + (isLiked ? " liked" : "");
    likeBtn.setAttribute("aria-label", isLiked ? "Unlike" : "Like");
    likeBtn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>';
    likeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleLike({ urls: urls }, likeBtn, item);
    });
    item.appendChild(likeBtn);

    var skeleton = document.createElement("div");
    skeleton.className = "skeleton gallery-item-skeleton";
    item.style.minHeight = "200px";

    var urlHints = isGif ? "GIF" : formatPinimgUrlHints(url);
    var meta = document.createElement("div");
    meta.className = "gallery-item-meta";

    if (gifVideoUrl) {
      // X animated GIF — render as a silent looping video
      var vid = document.createElement("video");
      vid.autoplay = true;
      vid.loop = true;
      vid.muted = true;
      vid.setAttribute("playsinline", "");
      vid.setAttribute("data-orig-url", url);
      vid.src = gifVideoUrl;
      vid.onloadeddata = function () {
        if (skeleton.parentNode) skeleton.remove();
        item.style.minHeight = "";
        meta.textContent = "GIF";
      };
      vid.onerror = function () { item.remove(); };
      item.appendChild(vid);
    } else {
      var img = document.createElement("img");
      img.alt = "";
      img.decoding = "async";
      img.setAttribute("data-orig-url", url);
      img.onload = function () {
        if (skeleton.parentNode) skeleton.remove();
        item.style.minHeight = "";
        if (resFilter.enabled) {
          var est = estimateSizeFromUrl(url);
          if (est && !passesResolutionFilter(est.w, est.h)) {
            removeFilteredPost(item, postKey);
            return;
          }
        }
        meta.textContent = urlHints || "";
      };
      var thumbSrc = isGif ? url : thumbnailUrl(url);
      img.onerror = isGif
        ? function () {
            // GIF failed — fall back to JPEG thumbnail so the card still shows
            var fallback = thumbnailUrl(url);
            if (img.src !== fallback) { img.src = fallback; isGif = false; }
            else { item.remove(); }
          }
        : function () { item.remove(); };
      if (lazyImageObserver && !isGif) {
        img.setAttribute("data-lazy-src", thumbSrc);
      } else {
        img.loading = "lazy";
        img.src = thumbSrc;
      }
      item.appendChild(img);
    }
    item.appendChild(skeleton);
    meta.textContent = urlHints || "Loading\u2026";

    if (isGif) {
      var gifBadge = document.createElement("span");
      gifBadge.className = "gif-badge";
      gifBadge.textContent = "GIF";
      item.appendChild(gifBadge);
    }

    var cardSlideIndex = 0;

    if (urls.length > 1) {
      var badge = document.createElement("span");
      badge.className = "gallery-item-badge";
      badge.setAttribute("aria-label", urls.length + " images in this pin");
      badge.title = urls.length + " images in this pin";
      var stack = document.createElement("span");
      stack.className = "gallery-badge-stack";
      stack.setAttribute("aria-hidden", "true");
      var numEl = document.createElement("span");
      numEl.textContent = String(urls.length);
      badge.appendChild(stack);
      badge.appendChild(numEl);
      item.appendChild(badge);
    }

    // Card-level multi-image navigation (dots + prev/next arrows)
    if (urls.length > 1 && !gifVideoUrl) {
      var cardDotCount = Math.min(urls.length, 15);
      var cardDotsEl = document.createElement("div");
      cardDotsEl.className = "card-dots";
      for (var _d = 0; _d < cardDotCount; _d++) {
        var _dot = document.createElement("span");
        _dot.className = "card-dot" + (_d === 0 ? " active" : "");
        cardDotsEl.appendChild(_dot);
      }
      item.appendChild(cardDotsEl);

      var cardPrevBtn = document.createElement("button");
      cardPrevBtn.type = "button";
      cardPrevBtn.className = "card-nav-btn card-nav-prev";
      cardPrevBtn.setAttribute("aria-label", "Previous image");
      cardPrevBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';

      var cardNextBtn = document.createElement("button");
      cardNextBtn.type = "button";
      cardNextBtn.className = "card-nav-btn card-nav-next";
      cardNextBtn.setAttribute("aria-label", "Next image");
      cardNextBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

      var _updateCardNavState = function () {
        var atStart = cardSlideIndex <= 0;
        var atEnd = cardSlideIndex >= urls.length - 1;
        cardPrevBtn.style.opacity = atStart ? "0" : "";
        cardPrevBtn.style.pointerEvents = atStart ? "none" : "";
        cardNextBtn.style.opacity = atEnd ? "0" : "";
        cardNextBtn.style.pointerEvents = atEnd ? "none" : "";
        var dots = cardDotsEl.querySelectorAll(".card-dot");
        dots.forEach(function (d, i) { d.classList.toggle("active", i === cardSlideIndex); });
      };

      var _navigateCard = function (dir) {
        var newIdx = cardSlideIndex + dir;
        if (newIdx < 0 || newIdx >= urls.length) return;
        cardSlideIndex = newIdx;
        if (img) img.src = thumbnailUrl(urls[cardSlideIndex]);
        _updateCardNavState();
      };

      cardPrevBtn.addEventListener("click", function (e) { e.stopPropagation(); _navigateCard(-1); });
      cardNextBtn.addEventListener("click", function (e) { e.stopPropagation(); _navigateCard(1); });

      item.appendChild(cardPrevBtn);
      item.appendChild(cardNextBtn);
      _updateCardNavState();
    }

    // Overlay
    var overlay = document.createElement("div");
    overlay.className = "overlay";

    var overlayBottom = document.createElement("div");
    overlayBottom.className = "overlay-bottom";

    // Left actions: copy URL, open pin, add to collection
    var leftActs = document.createElement("div");
    leftActs.className = "overlay-left-actions";

    var copyBtn = document.createElement("button");
    copyBtn.className = "overlay-action-btn";
    copyBtn.setAttribute("aria-label", "Copy image URL");
    copyBtn.title = "Copy image URL";
    copyBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    copyBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      navigator.clipboard.writeText(url).then(function () {
        showToast("\u2713 URL copied");
      }).catch(function () {
        showToast("\u2717 Copy failed");
      });
    });

    var openBtn = document.createElement("button");
    openBtn.className = "overlay-action-btn";
    openBtn.setAttribute("aria-label", "Open pin on Pinterest");
    openBtn.title = post.pin_url
      ? (post.source === "x" ? "View tweet on X" : "Open pin on Pinterest")
      : "Open image in browser";
    openBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
    openBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      openInBrowser(post.pin_url || url);
    });

    var colBtn = document.createElement("button");
    colBtn.className = "overlay-action-btn";
    colBtn.setAttribute("aria-label", "Add to collection");
    colBtn.title = "Add to collection";
    colBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>';
    colBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      showAddToCollectionDialog({ urls: urls });
    });

    leftActs.appendChild(copyBtn);
    leftActs.appendChild(openBtn);
    leftActs.appendChild(colBtn);

    // Download — grouped with the other actions
    var dlBtn = document.createElement("button");
    dlBtn.className = "download-btn";
    dlBtn.setAttribute("aria-label", "Download cover image");
    dlBtn.appendChild(createDownloadIcon());
    dlBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      downloadImage(downloadUrl);
    });
    leftActs.appendChild(dlBtn);

    overlayBottom.appendChild(leftActs);
    overlay.appendChild(overlayBottom);
    item.appendChild(overlay);
    item.appendChild(meta);

    item.addEventListener("click", function () {
      if (selectMode) {
        togglePostSelect(postKey, item);
        return;
      }
      openModalForPostByKey(postKey, cardSlideIndex);
    });

    if (lazyImageObserver) lazyImageObserver.observe(item);
    return item;
  }

  function openModalForPostByKey(postKey, startSlide) {
    for (var i = 0; i < feedPosts.length; i++) {
      var u = feedPosts[i].urls && feedPosts[i].urls[0];
      if (u && canonicalKeyFromPinimgUrl(u) === postKey) {
        openModalForPost(i, startSlide || 0);
        return;
      }
    }
  }

  function renderPosts(posts) {
    initGalleryCols();
    seenPostKeys = new Set();
    feedPosts = [];
    posts.forEach(function (p) {
      var post = { urls: (p.urls || []).slice(), pin_url: p.pin_url || null };
      if (!post.urls.length) return;
      var k = canonicalKeyFromPinimgUrl(post.urls[0]);
      if (!k || seenPostKeys.has(k)) return;
      seenPostKeys.add(k);
      feedPosts.push(post);
    });
    feedPosts.forEach(function (post, index) {
      var el = createGalleryItem(post, index, index);
      if (el) galleryCols[index % colCount].appendChild(el);
    });
  }

  function appendPosts(newPosts) {
    var anim = 0;
    newPosts.forEach(function (raw) {
      var post = { urls: (raw.urls || []).slice(), pin_url: raw.pin_url || null, source: raw.source || null };
      if (!post.urls.length) return;
      var k = canonicalKeyFromPinimgUrl(post.urls[0]);
      if (!k || seenPostKeys.has(k)) return;
      seenPostKeys.add(k);
      feedPosts.push(post);
      var idx = feedPosts.length - 1;
      var el = createGalleryItem(post, anim, idx);
      anim += 1;
      if (el) galleryCols[idx % colCount].appendChild(el);
    });
  }

  function loadMoreHome() {
    if (homeLoadingMore || homeMoreExhausted) return;
    // Works regardless of currentTab; accumulates off-tab into homeSavedPosts.
    var onHome = currentTab === "home";
    if (onHome ? feedPosts.length < 1 : homeSavedPosts.length < 1) return;
    homeLoadingMore = true;
    var isBg = bgLoading;
    if (!isBg && onHome) setInfiniteLoading(true);
    var epoch = homeEpoch;
    var seenUrls = [];
    (onHome ? feedPosts : homeSavedPosts).forEach(function (p) {
      (p.urls || []).forEach(function (u) { seenUrls.push(u); });
    });
    fetch("/api/home/more", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seen_urls: seenUrls })
    })
      .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
      .then(function (pair) {
        if (epoch !== homeEpoch) return;
        var res = pair.res;
        var data = pair.data;
        if (res.status === 401) { homeMoreExhausted = true; homeSavedExhausted = true; return; }
        if (!res.ok || data.error) { homeMoreExhausted = true; homeSavedExhausted = true; return; }
        var next = normalizePostsPayload(data);
        if (next.length > 0) {
          if (currentTab === "home") {
            var lenBefore = feedPosts.length;
            appendPosts(next);
            // Keep canonical store in sync with what's now in the DOM
            homeSavedPosts = feedPosts.slice();
            homeSavedKeys = new Set(seenPostKeys);
            if (!data.has_more || next.length === 0 || feedPosts.length === lenBefore) {
              homeMoreExhausted = true;
            }
          } else {
            // Off home tab: accumulate into homeSavedPosts without touching the DOM
            var added = 0;
            next.forEach(function (raw) {
              var post = { urls: (raw.urls || []).slice(), pin_url: raw.pin_url || null };
              if (!post.urls.length) return;
              var k = canonicalKeyFromPinimgUrl(post.urls[0]);
              if (!k || homeSavedKeys.has(k)) return;
              homeSavedKeys.add(k);
              homeSavedPosts.push(post);
              added++;
            });
            if (!data.has_more || added === 0) homeMoreExhausted = true;
          }
        } else {
          homeMoreExhausted = true;
        }
        homeSavedExhausted = homeMoreExhausted;
        if (currentTab === "home") {
          rafTwice(ensureInfiniteFeedBuffer);
          if (!homeMoreExhausted && data.has_more) {
            scheduleHomeDeepPrefetch(true);
          }
        }
      })
      .catch(function () {
        if (epoch !== homeEpoch) return;
        homeMoreExhausted = true;
        homeSavedExhausted = true;
      })
      .finally(function () {
        homeLoadingMore = false;
        if (epoch !== homeEpoch) return;
        if (!isBg && onHome) setInfiniteLoading(false);
        if (currentTab === "home") {
          scheduleScrollPrefetchCheck();
          rafTwice(ensureInfiniteFeedBuffer);
        }
        scheduleBgLoad();
      });
  }

  function loadMoreSearch() {
    if (loadingMoreGrid || searchMoreExhausted || currentTab !== "search") return;
    if (feedPosts.length < 1 || !lastSearchQuery) return;
    loadingMoreGrid = true;
    setInfiniteLoading(true);
    var epoch = feedEpoch;
    fetch("/api/search/more", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: lastSearchQuery, seen_urls: flattenSeenUrls() })
    })
      .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
      .then(function (pair) {
        if (epoch !== feedEpoch) return;
        var res = pair.res;
        var data = pair.data;
        if (res.status === 401) {
          searchMoreExhausted = true;
          return;
        }
        if (!res.ok || data.error) {
          showToast("✗ " + ((data && data.error) || "Could not load more"));
          searchMoreExhausted = true;
          return;
        }
        var next = normalizePostsPayload(data);
        var lenBefore = feedPosts.length;
        if (next.length > 0) appendPosts(next);
        if (!data.has_more || next.length === 0 || feedPosts.length === lenBefore) {
          searchMoreExhausted = true;
        } else {
          rafTwice(ensureInfiniteFeedBuffer);
          scheduleSearchDeepPrefetch(!!data.has_more);
        }
      })
      .catch(function () {
        if (epoch !== feedEpoch) return;
        showToast("✗ Could not load more");
        searchMoreExhausted = true;
      })
      .finally(function () {
        loadingMoreGrid = false;
        if (epoch !== feedEpoch) return;
        setInfiniteLoading(false);
        scheduleScrollPrefetchCheck();
        rafTwice(ensureInfiniteFeedBuffer);
      });
  }

  function setupInfiniteObserver() {
    if (!infiniteSentinel || typeof IntersectionObserver === "undefined") return;
    if (infiniteScrollObs) {
      try {
        infiniteScrollObs.disconnect();
      } catch (e) {}
      infiniteScrollObs = null;
    }
    infiniteScrollObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        if (currentTab === "home") {
          loadMoreHome();
        } else if (currentTab === "search") {
          loadMoreSearch();
        } else if (currentTab === "artists") {
          loadMoreX();
        }
      });
    }, { root: null, rootMargin: infiniteObserverRootMargin(), threshold: 0 });
    infiniteScrollObs.observe(infiniteSentinel);
  }

  function scheduleInfiniteObserverRelayout() {
    if (infiniteObsResizeTimer) clearTimeout(infiniteObsResizeTimer);
    infiniteObsResizeTimer = setTimeout(function () {
      infiniteObsResizeTimer = null;
      setupInfiniteObserver();
    }, 250);
  }

  // ─── Modal dots ───
  function updateModalDots() {
    if (!modalDots) return;
    var n = modalSlideshowUrls.length;
    if (n < 2) { modalDots.classList.add("hidden"); return; }
    modalDots.innerHTML = "";
    modalDots.classList.remove("hidden");
    var cap = Math.min(n, 20);
    for (var i = 0; i < cap; i++) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "modal-dot" + (i === modalSlideIndex ? " active" : "");
      dot.setAttribute("aria-label", "Image " + (i + 1));
      (function (idx) {
        dot.addEventListener("click", function () { jumpModalToIndex(idx); });
      })(i);
      modalDots.appendChild(dot);
    }
  }

  function jumpModalToIndex(index) {
    if (index < 0 || index >= modalSlideshowUrls.length || index === modalSlideIndex) return;
    modalSlideIndex = index;
    currentImageUrl = modalSlideshowUrls[modalSlideIndex];
    resetModalZoom();
    modalImg.style.opacity = "0";
    setTimeout(function () {
      modalImg.src = currentImageUrl;
      modalImg.onload = function () { modalImg.style.opacity = "1"; };
    }, 150);
    updateNavButtons();
    updateModalSlideshowHint();
  }

  // ─── Modal zoom helpers ───
  function applyModalZoom() {
    var el = modalImg;
    if (!el || el.style.display === "none") return;
    var tx = modalPanX / modalZoom;
    var ty = modalPanY / modalZoom;
    el.style.transform = "scale(" + modalZoom + ") translate(" + tx + "px, " + ty + "px)";
    el.classList.toggle("is-zoomed", modalZoom > 1);
    el.classList.toggle("zoomable", true);
  }

  function resetModalZoom() {
    modalZoom = 1;
    modalPanX = 0;
    modalPanY = 0;
    if (modalImg) {
      modalImg.style.transform = "";
      modalImg.classList.remove("is-zoomed", "is-dragging");
    }
  }

  // ─── Modal (one Pinterest pin; arrows step through that pin's images) ───
  function updateModalDownloadAllVisibility() {
    if (!modalDownloadAll) return;
    modalDownloadAll.classList.toggle("hidden", modalSlideshowUrls.length < 2);
  }

  function updateModalSlideshowHint() {
    if (!modalSlideshowHint) return;
    var n = modalSlideshowUrls.length;
    // Only show the text hint when there are too many images for dots (> 20)
    if (n > 20) {
      modalSlideshowHint.classList.remove("hidden");
      modalSlideshowHint.textContent = n + " photos \u2014 use arrows or keyboard \u2190 \u2192.";
    } else {
      modalSlideshowHint.classList.add("hidden");
      modalSlideshowHint.textContent = "";
    }
  }

  function clearModalRelated() {
    if (!modalRelated) return;
    modalRelated.classList.add("hidden");
    modalRelated.innerHTML = "";
  }

  function renderModalRelatedPosts(posts) {
    if (!modalRelated) return;
    modalRelated.innerHTML = "";
    if (!posts || !posts.length) {
      modalRelated.classList.remove("hidden");
      var emptyRel = document.createElement("div");
      emptyRel.className = "modal-related-loading-empty";
      emptyRel.textContent = "No similar pins found.";
      modalRelated.appendChild(emptyRel);
      return;
    }
    modalRelated.classList.remove("hidden");
    var label = document.createElement("div");
    label.className = "modal-related-label";
    label.textContent = "More like this";
    var track = document.createElement("div");
    track.className = "modal-related-grid";
    posts.forEach(function (raw) {
      var urls = raw.urls || [];
      if (!urls.length) return;
      var thumb = document.createElement("div");
      thumb.className = "modal-related-thumb";
      thumb.setAttribute("role", "button");
      thumb.setAttribute("tabindex", "0");
      thumb.setAttribute("aria-label", "Open similar pin");

      var relSlideIndex = 0;

      var im = document.createElement("img");
      im.alt = "";
      im.decoding = "async";
      im.onerror = function () {
        var tried = parseInt(im.getAttribute("data-url-idx") || "0", 10);
        tried += 1;
        if (tried < urls.length) {
          im.setAttribute("data-url-idx", tried);
          im.src = thumbnailUrl(urls[tried]);
        } else {
          thumb.style.display = "none";
        }
      };
      im.src = thumbnailUrl(urls[0]);
      thumb.appendChild(im);

      // Multi-image nav for related thumbs
      if (urls.length > 1) {
        var relDotCount = Math.min(urls.length, 10);
        var relDotsEl = document.createElement("div");
        relDotsEl.className = "rel-thumb-dots";
        for (var _rd = 0; _rd < relDotCount; _rd++) {
          var _rdot = document.createElement("span");
          _rdot.className = "rel-thumb-dot" + (_rd === 0 ? " active" : "");
          relDotsEl.appendChild(_rdot);
        }
        thumb.appendChild(relDotsEl);

        var relPrev = document.createElement("button");
        relPrev.type = "button";
        relPrev.className = "rel-thumb-nav rel-thumb-nav-prev";
        relPrev.setAttribute("aria-label", "Previous image");
        relPrev.innerHTML = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';

        var relNext = document.createElement("button");
        relNext.type = "button";
        relNext.className = "rel-thumb-nav rel-thumb-nav-next";
        relNext.setAttribute("aria-label", "Next image");
        relNext.innerHTML = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

        var _updateRelNav = function () {
          relPrev.style.opacity = relSlideIndex <= 0 ? "0" : "";
          relPrev.style.pointerEvents = relSlideIndex <= 0 ? "none" : "";
          relNext.style.opacity = relSlideIndex >= urls.length - 1 ? "0" : "";
          relNext.style.pointerEvents = relSlideIndex >= urls.length - 1 ? "none" : "";
          relDotsEl.querySelectorAll(".rel-thumb-dot").forEach(function (d, i) {
            d.classList.toggle("active", i === relSlideIndex);
          });
        };

        relPrev.addEventListener("click", function (e) {
          e.stopPropagation();
          if (relSlideIndex <= 0) return;
          relSlideIndex--;
          im.src = thumbnailUrl(urls[relSlideIndex]);
          _updateRelNav();
        });

        relNext.addEventListener("click", function (e) {
          e.stopPropagation();
          if (relSlideIndex >= urls.length - 1) return;
          relSlideIndex++;
          im.src = thumbnailUrl(urls[relSlideIndex]);
          _updateRelNav();
        });

        thumb.appendChild(relPrev);
        thumb.appendChild(relNext);
        _updateRelNav();
      }

      var postCopy = { urls: urls.slice(), pin_url: raw.pin_url || null };
      thumb.addEventListener("click", function (e) {
        e.stopPropagation();
        openModalForSimilarPost(postCopy, relSlideIndex);
      });
      thumb.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openModalForSimilarPost(postCopy, relSlideIndex); }
      });
      track.appendChild(thumb);
    });
    if (!track.children.length) {
      modalRelated.classList.add("hidden");
      return;
    }
    modalRelated.appendChild(label);
    modalRelated.appendChild(track);
  }

  function loadModalRelated() {
    if (!modalRelated) return;
    modalRelatedReqId += 1;
    var req = modalRelatedReqId;
    if (!modalSourcePost || !(modalSourcePost.urls || []).length) {
      clearModalRelated();
      return;
    }
    clearModalRelated();

    var pinUrl = (modalSourcePost.pin_url || "").trim();
    if (!pinUrl || pinUrl.indexOf("pinterest.com") === -1) {
      // No Pinterest pin URL — related pins not available.
      return;
    }

    modalRelated.classList.remove("hidden");
    var sectionLabel = document.createElement("div");
    sectionLabel.className = "modal-related-label";
    sectionLabel.textContent = "More like this";
    modalRelated.appendChild(sectionLabel);
    var loadingEl = document.createElement("div");
    loadingEl.className = "modal-related-loading";
    loadingEl.innerHTML =
      '<div class="modal-related-loading-header">' +
        '<div class="modal-related-loading-spinner"></div>' +
        '<span class="modal-related-loading-text">Fetching similar pins</span>' +
      '</div>' +
      '<div class="modal-related-skeleton">' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
        '<div class="modal-related-skeleton-card"></div>' +
      '</div>';
    modalRelated.appendChild(loadingEl);

    fetch("/api/pin/related", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pin_url: pinUrl,
        exclude_urls: (modalSourcePost.urls || []).slice()
      })
    })
      .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
      .then(function (pair) {
        if (req !== modalRelatedReqId) return;
        if (!pair.res.ok || (pair.data && pair.data.error)) {
          loadingEl.className = "modal-related-loading-empty";
          loadingEl.innerHTML = "";
          loadingEl.textContent = (pair.data && pair.data.error) ? pair.data.error : "Could not load similar pins.";
          return;
        }
        var posts = (pair.data && pair.data.posts) ? pair.data.posts : [];
        renderModalRelatedPosts(posts);
      })
      .catch(function () {
        if (req !== modalRelatedReqId) return;
        loadingEl.className = "modal-related-loading-empty";
        loadingEl.innerHTML = "";
        loadingEl.textContent = "Could not load similar pins.";
      });
  }

  function _resetModalScroll() {
    if (modalContent) modalContent.scrollTop = 0;
    if (modalStage) { modalStage.style.transform = ""; modalStage.style.opacity = ""; }
  }

  function openModalForSimilarPost(post, startSlide) {
    if (!post || !post.urls || !post.urls.length) return;
    modalPostIndex = -1;
    modalSourcePost = { urls: post.urls.slice(), pin_url: post.pin_url || null };
    modalSlideshowUrls = modalSourcePost.urls.slice();
    modalSlideIndex = (startSlide > 0 && startSlide < modalSlideshowUrls.length) ? startSlide : 0;
    currentImageUrl = modalSlideshowUrls[modalSlideIndex];
    _setModalMedia(post, currentImageUrl);
    _resetModalScroll();
    modal.classList.add("active");
    document.body.style.overflow = "hidden";
    updateNavButtons();
    updateModalDownloadAllVisibility();
    updateModalSlideshowHint();
    loadModalRelated();
  }

  function _setModalMedia(post, imageUrl) {
    var gifUrl = post && post.gif_video_url;
    if (gifUrl && modalVideo) {
      modalImg.style.display = "none";
      modalVideo.style.display = "";
      modalVideo.src = gifUrl;
    } else {
      if (modalVideo) { modalVideo.style.display = "none"; modalVideo.src = ""; }
      modalImg.style.display = "";
      modalImg.style.opacity = "1";
      modalImg.src = imageUrl;
    }
  }

  function openModalForPost(postIndex, startSlide) {
    var post = feedPosts[postIndex];
    if (!post || !post.urls || !post.urls.length) return;
    modalPostIndex = postIndex;
    modalSourcePost = { urls: post.urls.slice(), pin_url: post.pin_url || null, gif_video_url: post.gif_video_url || null };
    modalSlideshowUrls = post.urls.slice();
    modalSlideIndex = (startSlide > 0 && startSlide < modalSlideshowUrls.length) ? startSlide : 0;
    currentImageUrl = modalSlideshowUrls[modalSlideIndex];
    _setModalMedia(post, currentImageUrl);
    _resetModalScroll();
    modal.classList.add("active");
    document.body.style.overflow = "hidden";
    updateNavButtons();
    updateModalDownloadAllVisibility();
    updateModalSlideshowHint();
    loadModalRelated();
  }

  function closeModal() {
    modalRelatedReqId += 1;
    clearModalRelated();
    modalSourcePost = null;
    resetModalZoom();
    _modalDragMode = null;
    if (modalSlideshowHint) {
      modalSlideshowHint.classList.add("hidden");
      modalSlideshowHint.textContent = "";
    }
    if (modalSlideCounter) modalSlideCounter.classList.add("hidden");
    if (modalDots) { modalDots.innerHTML = ""; modalDots.classList.add("hidden"); }
    modal.classList.remove("active");
    document.body.style.overflow = "";
    if (modalDownloadAll) modalDownloadAll.classList.add("hidden");
    setTimeout(function () {
      modalImg.src = "";
      if (modalVideo) { modalVideo.src = ""; modalVideo.style.display = "none"; }
      modalImg.style.display = "";
      currentImageUrl = "";
      modalSlideIndex = 0;
      modalPostIndex = -1;
      modalSlideshowUrls = [];
    }, 300);
  }

  function navigateModal(direction) {
    if (modalSlideshowUrls.length === 0) return;
    var newIndex = modalSlideIndex + direction;
    if (newIndex < 0 || newIndex >= modalSlideshowUrls.length) return;
    modalSlideIndex = newIndex;
    currentImageUrl = modalSlideshowUrls[modalSlideIndex];
    resetModalZoom();
    modalImg.style.opacity = "0";
    setTimeout(function () {
      modalImg.src = currentImageUrl;
      modalImg.onload = function () {
        modalImg.style.opacity = "1";
      };
    }, 150);
    updateNavButtons();
    updateModalSlideshowHint();
  }

  function updateNavButtons() {
    var n = modalSlideshowUrls.length;
    if (modalPrev) modalPrev.style.display = n < 2 || modalSlideIndex <= 0 ? "none" : "";
    if (modalNext) modalNext.style.display = n < 2 || modalSlideIndex >= n - 1 ? "none" : "";
    if (modalSlideCounter) {
      if (n > 1) {
        modalSlideCounter.textContent = (modalSlideIndex + 1) + " / " + n;
        modalSlideCounter.classList.remove("hidden");
      } else {
        modalSlideCounter.classList.add("hidden");
      }
    }
    updateModalDots();
  }

  modalClose.addEventListener("click", closeModal);
  modalBackdrop.addEventListener("click", closeModal);

  // ─── Modal zoom (scroll wheel) ───
  if (modalStage) {
    modalStage.addEventListener("wheel", function (e) {
      if (!modal.classList.contains("active")) return;
      e.preventDefault();
      var delta = e.deltaY < 0 ? 0.18 : -0.18;
      modalZoom = Math.max(1, Math.min(5, modalZoom + delta));
      if (modalZoom === 1) { modalPanX = 0; modalPanY = 0; }
      applyModalZoom();
    }, { passive: false });

    // Double-click: zoom in (or reset if already zoomed)
    modalStage.addEventListener("dblclick", function (e) {
      if (e.target === modalImg) {
        if (modalZoom > 1) {
          resetModalZoom();
        } else {
          modalZoom = 2.5;
          applyModalZoom();
        }
      }
    });

    // Mousedown: start pan (when zoomed) or swipe nav (when not zoomed)
    modalStage.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      if (e.target === modalImg || e.target === modalVideo) {
        e.preventDefault();
        _modalDragStartX = e.clientX;
        _modalDragStartY = e.clientY;
        _modalDragMode = modalZoom > 1 ? "pan" : "swipe";
        _modalPanStartX = modalPanX;
        _modalPanStartY = modalPanY;
        if (_modalDragMode === "pan" && modalImg) {
          modalImg.classList.add("is-dragging");
        }
      }
    });
  }

  // Touch swipe in modal for multi-image navigation
  var _touchSwipeStartX = 0;
  var _touchSwipeStartY = 0;
  if (modalStage) {
    modalStage.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) return;
      _touchSwipeStartX = e.touches[0].clientX;
      _touchSwipeStartY = e.touches[0].clientY;
    }, { passive: true });

    modalStage.addEventListener("touchend", function (e) {
      if (modalSlideshowUrls.length < 2 || modalZoom > 1) return;
      var dx = e.changedTouches[0].clientX - _touchSwipeStartX;
      var dy = e.changedTouches[0].clientY - _touchSwipeStartY;
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) {
        navigateModal(dx < 0 ? 1 : -1);
      }
    }, { passive: true });
  }

  // Global mousemove/mouseup for pan and swipe
  document.addEventListener("mousemove", function (e) {
    if (!_modalDragMode) return;
    var dx = e.clientX - _modalDragStartX;
    var dy = e.clientY - _modalDragStartY;
    if (_modalDragMode === "pan") {
      modalPanX = _modalPanStartX + dx;
      modalPanY = _modalPanStartY + dy;
      applyModalZoom();
    }
  });

  document.addEventListener("mouseup", function (e) {
    if (!_modalDragMode) return;
    var dx = e.clientX - _modalDragStartX;
    var dy = e.clientY - _modalDragStartY;
    if (_modalDragMode === "swipe" && modalSlideshowUrls.length > 1) {
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) {
        navigateModal(dx < 0 ? 1 : -1);
      }
    }
    if (modalImg) modalImg.classList.remove("is-dragging");
    _modalDragMode = null;
  });

  // Shrink + fade the main image as the user scrolls down toward similar pins.
  // The stage scrolls naturally (no sticky); the transform just adds a gentle
  // scale-down so the image "compresses" as it exits the top of the view.
  if (modalContent && modalStage) {
    modalContent.addEventListener("scroll", function () {
      var s = modalContent.scrollTop;
      var stageH = modalStage.offsetHeight || 400;
      // t goes 0→1 as scrollTop covers the image height
      var t = Math.min(s / stageH, 1);
      var scale = 1 - t * 0.18;
      var opacity = 1 - t * 0.55;
      modalStage.style.transform = "scale(" + scale + ")";
      modalStage.style.opacity = String(Math.max(opacity, 0));
    });
  }

  if (modalPrev) modalPrev.addEventListener("click", function () { navigateModal(-1); });
  if (modalNext) modalNext.addEventListener("click", function () { navigateModal(1); });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (settingsPanel.classList.contains("visible")) {
        closeSettings();
      } else if (modal.classList.contains("active")) {
        closeModal();
      }
    }
    if (modal.classList.contains("active")) {
      if (e.key === "ArrowLeft") navigateModal(-1);
      if (e.key === "ArrowRight") navigateModal(1);
    }
  });

  modalDownload.addEventListener("click", function () {
    var dlUrl = (modalSourcePost && modalSourcePost.gif_video_url) || currentImageUrl;
    if (dlUrl) downloadImage(dlUrl);
  });

  if (modalDownloadAll) {
    modalDownloadAll.addEventListener("click", function (e) {
      e.stopPropagation();
      downloadAllInModal();
    });
  }

  // ─── Download ───
  function downloadAllInModal() {
    var urls = modalSlideshowUrls.slice();
    if (urls.length < 2) return;
    var ok = 0;
    var fail = 0;
    var i = 0;
    function step() {
      if (i >= urls.length) {
        var parts = [];
        if (ok) parts.push(ok + " saved");
        if (fail) parts.push(fail + " failed");
        showToast(parts.length ? ("✓ " + parts.join(", ")) : "✗ Download failed");
        return;
      }
      var u = urls[i++];
      fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: u })
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.success) ok += 1;
          else fail += 1;
        })
        .catch(function () {
          fail += 1;
        })
        .finally(step);
    }
    showToast("Downloading " + urls.length + " images…");
    step();
  }

  function downloadImage(url) {
    fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.success) {
          showToast("✓ Downloaded successfully");
        } else {
          showToast("✗ Download failed");
        }
      })
      .catch(function () {
        showToast("✗ Download failed");
      });
  }

  // ─── Toast ───
  function showToast(message) {
    toast.textContent = message;
    toast.classList.remove("hidden");
    requestAnimationFrame(function () {
      toast.classList.add("visible");
    });
    setTimeout(function () {
      toast.classList.remove("visible");
      setTimeout(function () {
        toast.classList.add("hidden");
      }, 400);
    }, 2500);
  }

  // ─── Settings ───
  function openSettings() {
    settingsPanel.classList.add("visible");
    settingsBackdrop.classList.add("visible");
    loadSettings();
    refreshAuthBadge();
  }

  function closeSettings() {
    settingsPanel.classList.remove("visible");
    settingsBackdrop.classList.remove("visible");
  }

  settingsBtn.addEventListener("click", openSettings);
  settingsClose.addEventListener("click", closeSettings);
  settingsBackdrop.addEventListener("click", closeSettings);

  // ─── Backup / Restore ───
  var exportBtn = document.getElementById("export-btn");
  var importBtn = document.getElementById("import-btn");
  var importFileInput = document.getElementById("import-file-input");

  if (exportBtn) {
    exportBtn.addEventListener("click", function () {
      exportBtn.disabled = true;
      fetch("/api/export")
        .then(function (res) {
          if (!res.ok) throw new Error("Export failed");
          return res.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = "japw_backup.json";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          showToast("Backup exported");
        })
        .catch(function () { showToast("Export failed"); })
        .finally(function () { exportBtn.disabled = false; });
    });
  }

  if (importBtn && importFileInput) {
    importBtn.addEventListener("click", function () {
      importFileInput.value = "";
      importFileInput.click();
    });

    importFileInput.addEventListener("change", function () {
      var file = importFileInput.files && importFileInput.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        var text = e.target.result;
        var data;
        try { data = JSON.parse(text); } catch (_) {
          showToast("Invalid backup file");
          return;
        }
        importBtn.disabled = true;
        fetch("/api/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        })
          .then(function (res) { return res.json(); })
          .then(function (body) {
            if (body.success) {
              showToast("Backup restored — restart to apply all changes");
              loadSettings();
            } else {
              showToast("Import error: " + (body.errors || [body.error]).join(", "));
            }
          })
          .catch(function () { showToast("Import failed"); })
          .finally(function () { importBtn.disabled = false; });
      };
      reader.readAsText(file);
    });
  }

  function loadSettings() {
    fetch("/api/settings")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        folderInput.value = data.download_folder || "";
        if (resolutionFilterEnabledCb) resolutionFilterEnabledCb.checked = !!data.resolution_filter_enabled;
        if (resolutionWidthInput) resolutionWidthInput.value = String(data.resolution_target_width || 1920);
        if (resolutionHeightInput) resolutionHeightInput.value = String(data.resolution_target_height || 1080);
        if (resolutionMatchModeSelect) {
          resolutionMatchModeSelect.value = data.resolution_match_mode === "exact" ? "exact" : "min";
        }
        if (filterPromotedCb) filterPromotedCb.checked = data.filter_promoted !== false;
        if (filterAiContentCb) filterAiContentCb.checked = !!data.filter_ai_content;
        applyResolutionConfigFromApi(data);
      });
  }

  if (resolutionFilterSaveBtn) {
    resolutionFilterSaveBtn.addEventListener("click", function () {
      var patch = {
        resolution_filter_enabled: !!(resolutionFilterEnabledCb && resolutionFilterEnabledCb.checked),
        resolution_target_width: parseInt(resolutionWidthInput && resolutionWidthInput.value, 10) || 1920,
        resolution_target_height: parseInt(resolutionHeightInput && resolutionHeightInput.value, 10) || 1080,
        resolution_match_mode: (resolutionMatchModeSelect && resolutionMatchModeSelect.value) || "min"
      };
      fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (pair) {
          if (!pair.ok) throw new Error("bad");
          return fetch("/api/settings");
        })
        .then(function (res) { return res.json(); })
        .then(function (full) {
          folderInput.value = full.download_folder || folderInput.value;
          if (resolutionFilterEnabledCb) resolutionFilterEnabledCb.checked = !!full.resolution_filter_enabled;
          if (resolutionWidthInput) resolutionWidthInput.value = String(full.resolution_target_width || 1920);
          if (resolutionHeightInput) resolutionHeightInput.value = String(full.resolution_target_height || 1080);
          if (resolutionMatchModeSelect) {
            resolutionMatchModeSelect.value = full.resolution_match_mode === "exact" ? "exact" : "min";
          }
          applyResolutionConfigFromApi(full);
          reapplyResolutionFilter();
          showToast("✓ Resolution filter saved");
        })
        .catch(function () {
          showToast("✗ Could not save filter");
        });
    });
  }

  function _saveContentFilterToggle(key, value) {
    var patch = {};
    patch[key] = value;
    fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.success) showToast(value ? "✓ Filter enabled" : "✓ Filter disabled"); })
      .catch(function () { showToast("✗ Could not save setting"); });
  }

  if (filterPromotedCb) {
    filterPromotedCb.addEventListener("change", function () {
      _saveContentFilterToggle("filter_promoted", filterPromotedCb.checked);
    });
  }

  if (filterAiContentCb) {
    filterAiContentCb.addEventListener("change", function () {
      _saveContentFilterToggle("filter_ai_content", filterAiContentCb.checked);
    });
  }

  if (pinterestConnectBtn) {
    pinterestConnectBtn.addEventListener("click", function () {
      fetch("/api/auth/login", { method: "POST" })
        .then(function (res) { return res.json().then(function (data) { return { res: res, data: data }; }); })
        .then(function (pair) {
          if (pair.res.status === 409) {
            showToast("✗ Sync already in progress");
            return;
          }
          showToast("Syncing with your browsers…");
          startLoginPoll();
          refreshAuthBadge();
        })
        .catch(function () {
          showToast("✗ Could not start sync");
        });
    });
  }

  if (pinterestOpenBrowserBtn) {
    pinterestOpenBrowserBtn.addEventListener("click", function () {
      fetch("/api/auth/open-browser", { method: "POST" })
        .then(function (res) {
          if (res.ok) {
            showToast("Opened Pinterest in your default browser");
          } else {
            showToast("✗ Could not open browser");
          }
        })
        .catch(function () {
          showToast("✗ Could not open browser");
        });
    });
  }

  if (pinterestDisconnectBtn) {
    pinterestDisconnectBtn.addEventListener("click", function () {
      fetch("/api/auth/logout", { method: "POST" })
        .then(function () {
          showToast("Pinterest session cleared");
          refreshAuthBadge();
          if (currentTab === "home") {
            loadHome();
          }
        })
        .catch(function () {
          showToast("✗ Disconnect failed");
        });
    });
  }

  folderPickerBtn.addEventListener("click", function () {
    if (window.pywebview) {
      window.pywebview.api.pick_folder().then(function (folder) {
        if (folder) {
          folderInput.value = folder;
          fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ download_folder: folder })
          });
        }
      });
    }
  });

  window.addEventListener("scroll", scheduleScrollPrefetchCheck, { passive: true });
  window.addEventListener("resize", function () {
    scheduleScrollPrefetchCheck();
    scheduleInfiniteObserverRelayout();
    syncFilterBarTop();
  }, { passive: true });
  setupLazyImageObserver();
  setupInfiniteObserver();
  beginSplash();
  fetch("/api/settings")
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (searchPinscrapeWhenLoggedInCb) {
        searchPinscrapeWhenLoggedInCb.checked = !!data.search_use_pinscrape_when_logged_in;
      }
      applyResolutionConfigFromApi(data);
    })
    .catch(function () { /* offline */ })
    .finally(function () {
      refreshAuthBadge();
      loadLikedState();
      loadSearchHistory();
      setTab("home");
    });

})();
