import json
import re
import subprocess
import textwrap
import unittest

from ai_progress_monitor.web import HTML


class WebUiBehaviorTests(unittest.TestCase):
    def test_pet_frontend_behaviors_match_prd(self):
        script = _main_script().replace("\nload();\n", "\n")
        result = subprocess.run(
            ["node", "-e", _node_harness(script)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["badgeText"], "3")
        self.assertIn("badge-needs-action", payload["badgeClass"])
        self.assertEqual(payload["needsActionPetSrc"], "/assets/pet/needs-action.png")
        self.assertEqual(payload["mixedSixBadgeText"], "6")
        self.assertIn("badge-needs-action", payload["mixedSixBadgeClass"])
        self.assertEqual(payload["runningPairBadgeText"], "2")
        self.assertIn("badge-running", payload["runningPairBadgeClass"])
        self.assertEqual(payload["idleTripleBadgeText"], "3")
        self.assertIn("badge-idle", payload["idleTripleBadgeClass"])
        self.assertEqual(payload["bubbleTitles"][0], "checkout-flow · Codex #2 · 待处理")
        self.assertIn("checkout-flow · Codex #1 · 进行中", payload["bubbleTitles"])
        self.assertIn("docs · 空闲", payload["bubbleTitles"])
        self.assertIn("checkout-flow · Claude #1 · 进行中", payload["sameFolderMixedToolTitles"])
        self.assertIn("checkout-flow · Codex #1 · 待处理", payload["sameFolderMixedToolTitles"])
        self.assertEqual(payload["stableLabelsBefore"], {"codex-stable-1": "checkout-flow · Codex #1 · 进行中", "codex-stable-2": "checkout-flow · Codex #2 · 空闲"})
        self.assertEqual(payload["stableLabelsAfter"], {"codex-stable-2": "checkout-flow · Codex #2 · 待处理", "codex-stable-1": "checkout-flow · Codex #1 · 空闲"})
        self.assertEqual(payload["singleDesktopNoFolderTitles"], ["Codex 对话 · 空闲"])
        self.assertEqual(payload["multiDesktopNoFolderLabels"], {"desktop-1": "Codex 对话 #1 · 空闲", "desktop-2": "Codex 对话 #2 · 进行中"})
        self.assertEqual(payload["readableDesktopNoFolderTitles"], ["Codex · hello · 空闲"])
        self.assertEqual(payload["codexGeneratedDesktopFolderTitles"], ["Codex · hello · 空闲"])
        self.assertEqual(payload["codexRealProjectFolderTitles"], ["20260703AIcoding · 进行中"])
        self.assertNotIn("SECRET", payload["bubbleHtml"])
        self.assertNotIn("Yes", payload["bubbleHtml"])
        self.assertEqual(payload["focusCallCount"], 0)
        self.assertEqual(payload["nativeFocusMessageCount"], 1)
        self.assertEqual(payload["actionCallCount"], 0)
        self.assertEqual(payload["focusSessionId"], "codex-2")
        self.assertTrue(payload["opened"])
        self.assertFalse(payload["closed"])
        self.assertEqual(payload["messagesAfterLeftClicks"], ["resize:bubbles", "resize:compact"])
        self.assertEqual(payload["petPositionAfterOpen"], {"left": "", "top": "", "right": "", "bottom": ""})
        self.assertEqual(payload["petPositionAfterClose"], {"left": "", "top": "", "right": "", "bottom": ""})
        self.assertFalse(payload["openedAfterDragClick"])
        self.assertEqual(payload["messagesAfterDragClick"], [])
        self.assertEqual(payload["messagesAfterRealDrag"], ["start-window-drag", "stop-window-drag"])
        self.assertFalse(payload["realDragBubbleOpen"])
        self.assertEqual(payload["messagesAfterHide"][-1], "hide")
        self.assertEqual(payload["restoreState"]["display"], "")
        self.assertFalse(payload["restoreState"]["bubbleOpen"])
        self.assertEqual(payload["restoreState"]["position"], {"left": "", "top": "", "right": "", "bottom": ""})
        self.assertEqual(payload["messagesAfterRestore"][-1], "resize:compact")
        self.assertEqual(payload["emptyBadgeText"], "")
        self.assertNotIn("show", payload["emptyBadgeClass"])
        self.assertIn("idle", payload["emptyPetClass"])
        self.assertIn("暂无 Claude/Codex 会话", payload["emptyBubbleHtml"])
        self.assertEqual(payload["runningBadgeText"], "1")
        self.assertIn("badge-running", payload["runningBadgeClass"])
        self.assertIn("running", payload["runningPetClass"])
        self.assertEqual(payload["runningPetSrc"], "/assets/pet/running.png")
        self.assertEqual(payload["runningBubbleTitles"], ["pricing-page · 进行中"])
        self.assertEqual(payload["idleBadgeText"], "1")
        self.assertIn("badge-idle", payload["idleBadgeClass"])
        self.assertIn("idle", payload["idlePetClass"])
        self.assertEqual(payload["idlePetSrc"], "/assets/pet/idle.png")
        self.assertEqual(payload["idleBubbleTitles"], ["release-checklist · 空闲"])
        self.assertEqual(payload["processOnlyBadgeText"], "1")
        self.assertIn("badge-running", payload["processOnlyBadgeClass"])
        self.assertIn("running", payload["processOnlyPetClass"])
        self.assertEqual(payload["processOnlyBubbleTitles"], ["checkout-flow · 进行中"])
        self.assertNotIn("弱识别", payload["processOnlyBubbleHtml"])
        self.assertNotIn("仅确认 CLI 会话存在", payload["processOnlyBubbleHtml"])
        self.assertEqual(payload["messagesAfterRightPointerDown"], [])
        self.assertFalse(payload["rightPointerDragging"])
        self.assertFalse(payload["rightPointerBubbleOpen"])
        self.assertTrue(payload["contextMenuPrevented"])
        self.assertTrue(payload["contextMenuOpen"])
        self.assertEqual(payload["contextMenuLeft"], "50px")
        self.assertEqual(payload["contextMenuTop"], "60px")
        self.assertEqual(payload["messagesAfterContextMenuOpen"], [])
        self.assertEqual(payload["messagesAfterContextHide"][-1], "hide")
        self.assertFalse(payload["contextMenuOpenAfterHide"])
        self.assertEqual(payload["messagesAfterContextQuit"][-1], "quit")
        self.assertFalse(payload["contextMenuOpenAfterQuit"])


def _main_script() -> str:
    scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
    return scripts[-1]


def _node_harness(script: str) -> str:
    return textwrap.dedent(
        f"""
        const vm = require("node:vm");
        const assert = require("node:assert/strict");
        const script = {json.dumps(script)};

        class ClassList {{
          constructor() {{ this.items = new Set(); }}
          add(...names) {{ names.forEach(name => this.items.add(name)); }}
          remove(...names) {{ names.forEach(name => this.items.delete(name)); }}
          contains(name) {{ return this.items.has(name); }}
          toggle(name, force) {{
            const next = force === undefined ? !this.items.has(name) : Boolean(force);
            if (next) this.items.add(name); else this.items.delete(name);
            return next;
          }}
          toString() {{ return Array.from(this.items).join(" "); }}
        }}

        class Element {{
          constructor(id) {{
            this.id = id;
            this.classList = new ClassList();
            this.style = {{}};
            this.dataset = {{}};
            this.children = [];
            this.textContent = "";
            this.offsetWidth = id === "pet" ? 150 : 260;
            this.offsetHeight = id === "pet" ? 136 : 120;
            this.scrollHeight = 120;
            this.listeners = {{}};
            this._innerHTML = "";
          }}
          set className(value) {{
            this.classList = new ClassList();
            String(value).split(/\\s+/).filter(Boolean).forEach(name => this.classList.add(name));
          }}
          get className() {{ return this.classList.toString(); }}
          set innerHTML(value) {{
            this._innerHTML = String(value);
            this.children = [];
            const itemRegex = /<button class="session-bubble ([^"]+)" type="button"([^>]*)>\\s*<span class="bubble-title">([^<]+)<\\/span>/g;
            let match;
            while ((match = itemRegex.exec(this._innerHTML))) {{
              const attrs = match[2];
              const idMatch = attrs.match(/data-session-id="([^"]*)"/);
              const sessionId = idMatch ? idMatch[1] : "";
              const child = new Element(`bubble-${{sessionId}}`);
              child.classList.add("session-bubble", match[1]);
              for (const attr of attrs.matchAll(/data-([a-z-]+)="([^"]*)"/g)) {{
                const key = attr[1].replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase());
                child.dataset[key] = attr[2];
              }}
              child.titleText = match[3];
              this.children.push(child);
            }}
          }}
          get innerHTML() {{ return this._innerHTML; }}
          addEventListener(name, handler) {{ this.listeners[name] = handler; }}
          contains(target) {{ return target === this || this.children.includes(target); }}
          setPointerCapture() {{}}
          getBoundingClientRect() {{
            if (this.id === "pet") return {{left: 180, top: 350, right: 330, bottom: 486, width: 150, height: 136}};
            return {{left: 20, top: 20, right: 320, bottom: 140, width: 300, height: 120}};
          }}
          querySelectorAll(selector) {{
            if (selector === ".session-bubble[data-session-id]") return this.children;
            if (selector === ".bubble-title") return this.children.map(child => ({{textContent: child.titleText}}));
            return [];
          }}
        }}

        const elements = {{
          pet: new Element("pet"),
          petArt: new Element("petArt"),
          petBadge: new Element("petBadge"),
          bubbleList: new Element("bubbleList"),
          petContextMenu: new Element("petContextMenu"),
          statusNote: new Element("statusNote"),
          hidePetMenuItem: new Element("hidePetMenuItem"),
          quitPetMenuItem: new Element("quitPetMenuItem"),
        }};
        elements.pet.classList.add("pet", "idle");

        const hostMessages = [];
        const fetchCalls = [];
        const windowListeners = {{}};
        const context = {{
          console,
          setTimeout: fn => {{ if (typeof fn === "function") fn(); return 0; }},
          clearTimeout: () => {{}},
          fetch: async (url, options={{}}) => {{
            fetchCalls.push({{url, options}});
            return {{ json: async () => ({{sessions: []}}), ok: true }};
          }},
          localStorage: {{ getItem: () => null, setItem: () => {{}}, removeItem: () => {{}} }},
          document: {{
            getElementById: id => elements[id],
          }},
          window: {{
            MONITOR_TOKEN: "test-token",
            innerWidth: 340,
            innerHeight: 500,
            resizeTo: () => {{}},
            requestAnimationFrame: fn => {{ if (typeof fn === "function") fn(); return 0; }},
            setTimeout: fn => {{ if (typeof fn === "function") fn(); return 0; }},
            clearTimeout: () => {{}},
	            addEventListener: (name, handler) => {{ windowListeners[name] = handler; }},
            webkit: {{
              messageHandlers: {{
                monitorWindow: {{
                  postMessage(message) {{
                    hostMessages.push(message);
                  }},
                }},
              }},
            }},
          }},
        }};
        context.globalThis = context;
        vm.createContext(context);
        vm.runInContext(script + "\\nglobalThis.__api = {{displayStatus,badgeState,renderBadge,renderBubbles,toggleBubbleList,hidePet,quitApp,restorePetFromHost}};", context);

        const api = context.__api;
        assert.equal(api.displayStatus({{status:"needs_action"}}), "needs_action");
        assert.equal(api.displayStatus({{status:"running"}}), "running");
        assert.equal(api.displayStatus({{status:"stuck"}}), "running");
        assert.equal(api.displayStatus({{status:"unknown"}}), "idle");
        assert.equal(api.displayStatus({{status:"running", monitoring_level:"process_only"}}), "running");

        const sessions = [
          {{session_id:"codex-1", title:"Codex - checkout-flow", tool:"codex", status:"running", monitoring_level:"full", summary:"SECRET running", safe_action:{{options:["Yes"]}}}},
          {{session_id:"codex-2", title:"Codex - checkout-flow", tool:"codex", status:"needs_action", monitoring_level:"full", summary:"SECRET wait", safe_action:{{options:["No"]}}}},
          {{session_id:"claude-1", title:"Claude Code - docs", tool:"claude_code", status:"idle", monitoring_level:"full", summary:"SECRET idle"}},
        ];
        api.renderBadge(sessions);
        api.renderBubbles(sessions);
        const badgeText = elements.petBadge.textContent;
        const badgeClass = elements.petBadge.classList.toString();
        const needsActionPetSrc = elements.petArt.src;
        const bubbleHtml = elements.bubbleList.innerHTML;
        const bubbleTitles = elements.bubbleList.children.map(child => child.titleText);

        const mixedSixSessions = [
          {{session_id:"mix-needs", title:"Codex - checkout-flow", tool:"codex", status:"needs_action", monitoring_level:"full"}},
          {{session_id:"mix-running-1", title:"Codex - api", tool:"codex", status:"running", monitoring_level:"full"}},
          {{session_id:"mix-running-2", title:"Claude Code - docs", tool:"claude_code", status:"running", monitoring_level:"full"}},
          {{session_id:"mix-idle-1", title:"Codex - release", tool:"codex", status:"idle", monitoring_level:"full"}},
          {{session_id:"mix-idle-2", title:"Claude Code - tests", tool:"claude_code", status:"idle", monitoring_level:"full"}},
          {{session_id:"mix-idle-3", title:"Codex - qa", tool:"codex", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBadge(mixedSixSessions);
        const mixedSixBadgeText = elements.petBadge.textContent;
        const mixedSixBadgeClass = elements.petBadge.classList.toString();

        api.renderBadge(mixedSixSessions.slice(1, 3));
        const runningPairBadgeText = elements.petBadge.textContent;
        const runningPairBadgeClass = elements.petBadge.classList.toString();

        api.renderBadge(mixedSixSessions.slice(3));
        const idleTripleBadgeText = elements.petBadge.textContent;
        const idleTripleBadgeClass = elements.petBadge.classList.toString();

        const sameFolderMixedTools = [
          {{session_id:"same-claude", title:"Claude Code - checkout-flow", tool:"claude_code", status:"running", monitoring_level:"full"}},
          {{session_id:"same-codex", title:"Codex - checkout-flow", tool:"codex", status:"needs_action", monitoring_level:"full"}},
        ];
        api.renderBubbles(sameFolderMixedTools);
        const sameFolderMixedToolTitles = elements.bubbleList.children.map(child => child.titleText);

        const stableSessionsBefore = [
          {{session_id:"codex-stable-1", title:"Codex - checkout-flow", tool:"codex", status:"running", monitoring_level:"full"}},
          {{session_id:"codex-stable-2", title:"Codex - checkout-flow", tool:"codex", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBubbles(stableSessionsBefore);
        const stableLabelsBefore = Object.fromEntries(elements.bubbleList.children.map(child => [child.dataset.sessionId, child.titleText]));
        const stableSessionsAfter = [
          {{session_id:"codex-stable-2", title:"Codex - checkout-flow", tool:"codex", status:"needs_action", monitoring_level:"full"}},
          {{session_id:"codex-stable-1", title:"Codex - checkout-flow", tool:"codex", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBubbles(stableSessionsAfter);
        const stableLabelsAfter = Object.fromEntries(elements.bubbleList.children.map(child => [child.dataset.sessionId, child.titleText]));

        const singleDesktopNoFolder = [
          {{session_id:"codex-session-he-l", title:"Codex Desktop - he-l", tool:"codex", surface:"desktop", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBubbles(singleDesktopNoFolder);
        const singleDesktopNoFolderTitles = elements.bubbleList.children.map(child => child.titleText);

        const multiDesktopNoFolder = [
          {{session_id:"desktop-1", title:"Codex Desktop - he-l", tool:"codex", surface:"desktop", status:"idle", monitoring_level:"full"}},
          {{session_id:"desktop-2", title:"Codex Desktop - x7-a", tool:"codex", surface:"desktop", status:"running", monitoring_level:"full"}},
        ];
        api.renderBubbles(multiDesktopNoFolder);
        const multiDesktopNoFolderLabels = Object.fromEntries(elements.bubbleList.children.map(child => [child.dataset.sessionId, child.titleText]));

        const readableDesktopNoFolder = [
          {{session_id:"desktop-readable", title:"Codex Desktop - hello", tool:"codex", surface:"desktop", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBubbles(readableDesktopNoFolder);
        const readableDesktopNoFolderTitles = elements.bubbleList.children.map(child => child.titleText);

        const codexGeneratedDesktopFolder = [
          {{session_id:"desktop-generated-folder", title:"Codex Desktop - hello", tool:"codex", surface:"desktop", status:"idle", monitoring_level:"full", cwd:"/Users/Gao/Documents/Codex/2026-07-07/hello", generated_conversation_path:true}},
        ];
        api.renderBubbles(codexGeneratedDesktopFolder);
        const codexGeneratedDesktopFolderTitles = elements.bubbleList.children.map(child => child.titleText);

        const codexRealProjectFolder = [
          {{session_id:"desktop-real-folder", title:"Codex Desktop - 20260703AIcoding", tool:"codex", surface:"desktop", status:"running", monitoring_level:"full", cwd:"/Users/Gao/Documents/20260703AIcoding"}},
        ];
        api.renderBubbles(codexRealProjectFolder);
        const codexRealProjectFolderTitles = elements.bubbleList.children.map(child => child.titleText);

        api.renderBubbles(sessions);
        elements.bubbleList.children[0].listeners.click();
        const focusCalls = fetchCalls.filter(call => String(call.url).includes("/api/focus"));
        const nativeFocusMessages = hostMessages.filter(message => message.type === "focus");
        const actionCalls = fetchCalls.filter(call => String(call.url).includes("/api/action"));
        const focusBody = nativeFocusMessages[0];

        hostMessages.length = 0;
        api.toggleBubbleList();
        const opened = elements.bubbleList.classList.contains("open");
        const petPositionAfterOpen = {{
          left: elements.pet.style.left || "",
          top: elements.pet.style.top || "",
          right: elements.pet.style.right || "",
          bottom: elements.pet.style.bottom || "",
        }};
        elements.pet.style.left = "220px";
        elements.pet.style.top = "330px";
        api.toggleBubbleList();
        const closed = elements.bubbleList.classList.contains("open");
        const messagesAfterLeftClicks = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        const petPositionAfterClose = {{
          left: elements.pet.style.left || "",
          top: elements.pet.style.top || "",
          right: elements.pet.style.right || "",
          bottom: elements.pet.style.bottom || "",
        }};

        hostMessages.length = 0;
        vm.runInContext("dragMoved = true; pet.onclick();", context);
        const openedAfterDragClick = elements.bubbleList.classList.contains("open");
        const messagesAfterDragClick = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));

        hostMessages.length = 0;
        elements.bubbleList.classList.remove("open");
        elements.pet.listeners.pointerdown({{button: 0, screenX: 80, screenY: 90, clientX: 80, clientY: 90, pointerId: 1}});
        windowListeners.pointermove({{screenX: 96, screenY: 110, clientX: 96, clientY: 110}});
        windowListeners.pointerup({{}});
        elements.pet.onclick();
        const messagesAfterRealDrag = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        const realDragBubbleOpen = elements.bubbleList.classList.contains("open");

        api.hidePet();
        const messagesAfterHide = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));

        elements.pet.style.display = "none";
        elements.pet.style.left = "260px";
        elements.pet.style.top = "380px";
        elements.bubbleList.classList.add("open");
        api.restorePetFromHost();
        const restoreState = {{
          display: elements.pet.style.display || "",
          bubbleOpen: elements.bubbleList.classList.contains("open"),
          position: {{
            left: elements.pet.style.left || "",
            top: elements.pet.style.top || "",
            right: elements.pet.style.right || "",
            bottom: elements.pet.style.bottom || "",
          }},
        }};
        const messagesAfterRestore = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));

        api.renderBadge([]);
        api.renderBubbles([]);
        const emptyBadgeText = elements.petBadge.textContent;
        const emptyBadgeClass = elements.petBadge.classList.toString();
        const emptyPetClass = elements.pet.classList.toString();
        const emptyBubbleHtml = elements.bubbleList.innerHTML;

        const runningSessions = [
          {{session_id:"running-1", title:"Codex - pricing-page", tool:"codex", status:"running", monitoring_level:"full"}},
        ];
        api.renderBadge(runningSessions);
        api.renderBubbles(runningSessions);
        const runningBadgeText = elements.petBadge.textContent;
        const runningBadgeClass = elements.petBadge.classList.toString();
        const runningPetClass = elements.pet.classList.toString();
        const runningPetSrc = elements.petArt.src;
        const runningBubbleTitles = elements.bubbleList.children.map(child => child.titleText);

        const idleSessions = [
          {{session_id:"idle-1", title:"Claude Code - release-checklist", tool:"claude_code", status:"idle", monitoring_level:"full"}},
        ];
        api.renderBadge(idleSessions);
        api.renderBubbles(idleSessions);
        const idleBadgeText = elements.petBadge.textContent;
        const idleBadgeClass = elements.petBadge.classList.toString();
        const idlePetClass = elements.pet.classList.toString();
        const idlePetSrc = elements.petArt.src;
        const idleBubbleTitles = elements.bubbleList.children.map(child => child.titleText);

        const processOnlySessions = [
          {{session_id:"process-1", title:"Claude Code CLI - checkout-flow", tool:"claude_code", status:"running", monitoring_level:"process_only"}},
        ];
        api.renderBadge(processOnlySessions);
        api.renderBubbles(processOnlySessions);
        const processOnlyBadgeText = elements.petBadge.textContent;
        const processOnlyBadgeClass = elements.petBadge.classList.toString();
        const processOnlyPetClass = elements.pet.classList.toString();
        const processOnlyBubbleTitles = elements.bubbleList.children.map(child => child.titleText);
        const processOnlyBubbleHtml = elements.bubbleList.innerHTML;

        hostMessages.length = 0;
        elements.pet.classList.remove("dragging");
        elements.bubbleList.classList.remove("open");
        elements.pet.listeners.pointerdown({{button: 2, buttons: 2, screenX: 50, screenY: 60, clientX: 50, clientY: 60, pointerId: 2}});
        const messagesAfterRightPointerDown = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        const rightPointerDragging = elements.pet.classList.contains("dragging");
        const rightPointerBubbleOpen = elements.bubbleList.classList.contains("open");

        hostMessages.length = 0;
        let contextMenuPrevented = false;
        elements.pet.listeners.contextmenu({{preventDefault() {{ contextMenuPrevented = true; }}, clientX: 50, clientY: 60}});
        const contextMenuOpen = elements.petContextMenu.classList.contains("open");
        const contextMenuLeft = elements.petContextMenu.style.left;
        const contextMenuTop = elements.petContextMenu.style.top;
        const messagesAfterContextMenuOpen = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        elements.hidePetMenuItem.onclick();
        const messagesAfterContextHide = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        const contextMenuOpenAfterHide = elements.petContextMenu.classList.contains("open");

        hostMessages.length = 0;
        elements.pet.listeners.contextmenu({{preventDefault() {{}}, clientX: 50, clientY: 60}});
        elements.quitPetMenuItem.onclick();
        const messagesAfterContextQuit = hostMessages.map(message => `${{message.type}}:${{message.mode || ""}}`.replace(/:$/, ""));
        const contextMenuOpenAfterQuit = elements.petContextMenu.classList.contains("open");

        process.stdout.write(JSON.stringify({{
          badgeText,
          badgeClass,
          needsActionPetSrc,
          mixedSixBadgeText,
          mixedSixBadgeClass,
          runningPairBadgeText,
          runningPairBadgeClass,
          idleTripleBadgeText,
          idleTripleBadgeClass,
	          bubbleTitles,
          sameFolderMixedToolTitles,
          stableLabelsBefore,
          stableLabelsAfter,
          singleDesktopNoFolderTitles,
          multiDesktopNoFolderLabels,
          readableDesktopNoFolderTitles,
          codexGeneratedDesktopFolderTitles,
          codexRealProjectFolderTitles,
	          bubbleHtml,
          focusCallCount: focusCalls.length,
          nativeFocusMessageCount: nativeFocusMessages.length,
          actionCallCount: actionCalls.length,
          focusSessionId: focusBody.session_id,
          opened,
          closed,
          messagesAfterLeftClicks,
          petPositionAfterOpen,
          petPositionAfterClose,
	          openedAfterDragClick,
	          messagesAfterDragClick,
          messagesAfterRealDrag,
          realDragBubbleOpen,
          messagesAfterHide,
          restoreState,
          messagesAfterRestore,
          emptyBadgeText,
          emptyBadgeClass,
          emptyPetClass,
          emptyBubbleHtml,
          runningBadgeText,
          runningBadgeClass,
          runningPetClass,
          runningPetSrc,
          runningBubbleTitles,
          idleBadgeText,
          idleBadgeClass,
          idlePetClass,
          idlePetSrc,
          idleBubbleTitles,
          processOnlyBadgeText,
          processOnlyBadgeClass,
          processOnlyPetClass,
          processOnlyBubbleTitles,
          processOnlyBubbleHtml,
          messagesAfterRightPointerDown,
          rightPointerDragging,
          rightPointerBubbleOpen,
          contextMenuPrevented,
          contextMenuOpen,
          contextMenuLeft,
          contextMenuTop,
          messagesAfterContextMenuOpen,
          messagesAfterContextHide,
          contextMenuOpenAfterHide,
          messagesAfterContextQuit,
          contextMenuOpenAfterQuit,
        }}));
        """
    )
