
    const $ = (id) => document.getElementById(id);

    function escapeHtml(text) {
      return String(text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: {"Content-Type": "application/json"},
        ...options
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "请求失败");
      }
      return data;
    }

    function renderTasks(tasks) {
      const pendingBody = $("taskTable");
      const completedBody = $("completedTaskTable");
      pendingBody.innerHTML = "";
      completedBody.innerHTML = "";

      const pendingTasks = (tasks || []).filter(task => !["success", "failed"].includes(task.status));
      const completedTasks = (tasks || []).filter(task => ["success", "failed"].includes(task.status));

      function appendRows(target, taskList) {
        for (const task of taskList) {
          const tr = document.createElement("tr");
          const statusClass = task.status === "success" ? "running" : (task.status === "failed" ? "failed" : "stopped");
          tr.innerHTML = `
            <td>${task.index}</td>
            <td>${escapeHtml(task.segment_name || "-")}</td>
            <td><span class="pill ${statusClass}">${escapeHtml(task.status || "-")}</span></td>
            <td><code>${escapeHtml(task.submit_id || "-")}</code></td>
            <td><code>${escapeHtml(task.command || "")}</code></td>
          `;
          target.appendChild(tr);
        }
      }

      appendRows(pendingBody, pendingTasks);
      appendRows(completedBody, completedTasks);

      if (!pendingTasks.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="5" class="hint">当前没有待执行任务</td>`;
        pendingBody.appendChild(tr);
      }

      if (!completedTasks.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="5" class="hint">当前还没有已完成任务</td>`;
        completedBody.appendChild(tr);
      }
    }

    function collectPayload() {
      return {
        dreamina: $("dreamina").value.trim(),
        queue_file: $("queueFile").value.trim(),
        output_root: $("outputRoot").value.trim(),
        state_file: $("stateFile").value.trim(),
        poll_interval: Number($("pollInterval").value || 30),
        timeout_seconds: Number($("timeoutSeconds").value || 10800),
        resume: $("resume").checked,
        stop_on_failure: $("stopOnFailure").checked,
        queue_content: $("queueContent").value
      };
    }

    async function refresh() {
      const data = await api("/api/status");
      const runner = data.runner || {};
      const state = data.state || {};
      const uiConfig = data.ui_config || {};
      const tasks = state.tasks || [];
      const successCount = tasks.filter(item => item.status === "success").length;
      const failCount = tasks.filter(item => item.status === "failed").length;

      const currentDreamina = $("dreamina").value.trim();
      const currentDreaminaValue = (currentDreamina && currentDreamina !== "dreamina") ? currentDreamina : "";
      const detectedDreamina = data.detected_dreamina || "";
      const runnerDreamina = (runner.running && runner.dreamina && runner.dreamina !== "dreamina") ? runner.dreamina : "";
      $("dreamina").value = runnerDreamina || uiConfig.dreamina || detectedDreamina || currentDreaminaValue || "dreamina";
      $("queueFile").value = data.queue_file || uiConfig.queue_file || "";
      $("outputRoot").value = data.output_root || uiConfig.output_root || "";
      $("stateFile").value = data.state_file || uiConfig.state_file || "";
      $("pollInterval").value = uiConfig.poll_interval || $("pollInterval").value || 30;
      $("timeoutSeconds").value = uiConfig.timeout_seconds || $("timeoutSeconds").value || 10800;
      $("resume").checked = runner.running ? $("resume").checked : !!uiConfig.resume;
      $("stopOnFailure").checked = runner.running ? $("stopOnFailure").checked : !!uiConfig.stop_on_failure;
      if (!isQueueEditorActive()) {
        $("queueContent").value = data.queue_content || queueDocumentToText(defaultQueueDocument());
        renderQueueList($("queueContent").value);
      }
      $("logTail").textContent = data.log_tail || "";
      $("totalCount").textContent = tasks.length;
      $("successCount").textContent = successCount;
      $("failCount").textContent = failCount;
      $("updatedAt").textContent = `最后刷新：${new Date().toLocaleString()}`;
      $("runnerPid").textContent = runner.pid || "-";
      $("runnerOutput").textContent = data.output_root || "-";

      const running = !!runner.running;
      $("runnerBadge").textContent = running ? "队列运行中" : "当前空闲";
      $("runnerState").innerHTML = running
        ? '<span class="pill running">running</span>'
        : '<span class="pill stopped">idle</span>';
      renderTasks(tasks);
    }

    function appendLines(textarea, lines) {
      const current = textarea.value.trim();
      const extra = (lines || []).join("\n");
      textarea.value = current ? `${current}\n${extra}` : extra;
      updatePreview().catch(() => {});
      renderRefs();
    }

    async function uploadFiles(kind, inputId, textareaId) {
      const input = $(inputId);
      if (!input.files || !input.files.length) {
        throw new Error("先选文件，再点上传。");
      }
      const form = new FormData();
      form.append("kind", kind);
      for (const file of input.files) {
        form.append("files", file);
      }
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "上传失败");
      }
      appendLines($(textareaId), data.paths || []);
      await loadMaterials();
      renderRefs();
      updateAutocomplete();
      input.value = "";
    }

    function collectMultimodalPayload() {
      return {
        prompt: $("mmPrompt").value,
        duration: $("mmDuration").value,
        ratio: $("mmRatio").value,
        model_version: $("mmModel").value,
        images: $("mmImages").value,
        videos: $("mmVideos").value,
        audios: $("mmAudios").value
      };
    }

    // Materials library - 必须在 getMaterialRefs 之前声明
    let allMaterials = [];
    let currentMaterialTab = 'all';
    let activeMaterial = null;
    let promptSelectionSnapshot = null;
    let queueEditorDirty = false;

    function listFromTextarea(id) {
      return $(id).value.split(/\n+/).map(item => item.trim()).filter(Boolean);
    }

    function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

    function materialShortName(mat) {
      if (mat && mat.stem) return mat.stem;
      return (mat?.name || "").replace(/^\d+-/, "").replace(/\.[^.]+$/, "");
    }

    function materialToken(mat) {
      return '@' + capitalize(mat.kind) + materialShortName(mat);
    }

    function materialLabel(mat) {
      return (mat?.name || "").split("/").pop() || materialShortName(mat);
    }

    function materialFieldId(kind) {
      return {
        image: "mmImages",
        video: "mmVideos",
        audio: "mmAudios",
      }[kind];
    }

    function queueItemId() {
      if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
      }
      return `segment-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    }

    function defaultQueueDocument() {
      return { version: 1, segments: [] };
    }

    const NEWLINE = String.fromCharCode(10);

    function normalizeSegment(segment, index) {
      const raw = (segment && typeof segment === "object" && !Array.isArray(segment)) ? { ...segment } : { command: String(segment || "") };
      const normalizeList = (value) => {
        if (Array.isArray(value)) {
          return value.map((item) => String(item || "").trim()).filter(Boolean);
        }
        return String(value || "").split(NEWLINE).map((item) => item.trim()).filter(Boolean);
      };
      return {
        id: String(raw.id || queueItemId()),
        name: String(raw.name || `片段${index}`).trim() || `片段${index}`,
        prompt: String(raw.prompt || "").trim(),
        command: String(raw.command || "").trim(),
        images: normalizeList(raw.images),
        videos: normalizeList(raw.videos),
        audios: normalizeList(raw.audios),
        duration: String(raw.duration || "").trim(),
        ratio: String(raw.ratio || "").trim(),
        model_version: String(raw.model_version || "").trim(),
      };
    }

    function commandLooksComplete(text) {
      let single = false;
      let double = false;
      let escaped = false;
      for (const ch of String(text || "")) {
        if (escaped) {
          escaped = false;
          continue;
        }
        if (ch === "\\") {
          escaped = true;
          continue;
        }
        if (ch === "'" && !double) {
          single = !single;
          continue;
        }
        if (ch === '"' && !single) {
          double = !double;
        }
      }
      return !single && !double;
    }

    function parseLegacyQueueCommands(raw) {
      const commands = [];
      let current = [];
      String(raw || "").split(NEWLINE).forEach((line) => {
        const stripped = line.trim();
        if (!current.length && (!stripped || stripped.startsWith("#"))) {
          return;
        }
        if (!stripped) {
          if (current.length && commandLooksComplete(current.join(NEWLINE))) {
            commands.push(current.join(NEWLINE).trim());
            current = [];
          }
          return;
        }
        current.push(stripped);
        const candidate = current.join(NEWLINE).trim();
        if (candidate && commandLooksComplete(candidate)) {
          commands.push(candidate);
          current = [];
        }
      });
      if (current.length) {
        commands.push(current.join(NEWLINE).trim());
      }
      return commands;
    }

    function extractPromptFromCommand(command) {
      const str = String(command || "");
      const marker = "--prompt";
      const start = str.indexOf(marker);
      if (start === -1) return "";
      let rest = str.slice(start + marker.length).trimStart();
      if (!rest) return "";
      const quote = rest[0];
      if (quote === "'" || quote === '"') {
        let value = "";
        let escaped = false;
        for (let i = 1; i < rest.length; i += 1) {
          const ch = rest[i];
          if (escaped) {
            value += ch;
            escaped = false;
            continue;
          }
          if (ch === "\\") {
            escaped = true;
            continue;
          }
          if (ch === quote) {
            return value;
          }
          value += ch;
        }
        return value.trim();
      }
      const nextFlag = rest.indexOf(" --");
      return (nextFlag === -1 ? rest : rest.slice(0, nextFlag)).trim();
    }

    function parseQueueDocument(text) {
      const raw = String(text || "").trim();
      if (!raw) return defaultQueueDocument();
      try {
        const parsed = JSON.parse(raw);
        const segments = Array.isArray(parsed)
          ? parsed
          : (parsed.segments || parsed.tasks || parsed.items || []);
        return {
          version: (parsed && typeof parsed === "object" && !Array.isArray(parsed) ? Number(parsed.version || 1) : 1),
          segments: Array.isArray(segments) ? segments.map((item, index) => normalizeSegment(item, index + 1)) : [],
        };
      } catch (_) {
        const commands = parseLegacyQueueCommands(raw);
        return {
          version: 1,
          segments: commands.map((command, index) => normalizeSegment({
            command,
            name: `片段${index + 1}`,
            prompt: extractPromptFromCommand(command)
          }, index + 1)),
        };
      }
    }

    function queueDocumentToText(doc) {
      const normalized = {
        version: Number(doc?.version || 1),
        segments: (doc?.segments || []).map((segment, index) => normalizeSegment(segment, index + 1)),
      };
      return JSON.stringify(normalized, null, 2);
    }

    function buildQueueSegmentFromForm() {
      const payload = collectMultimodalPayload();
      return normalizeSegment(
        {
          id: queueItemId(),
          name: $("mmSegmentName").value.trim() || `片段${Date.now()}`,
          prompt: payload.prompt,
          images: listFromTextarea("mmImages"),
          videos: listFromTextarea("mmVideos"),
          audios: listFromTextarea("mmAudios"),
          duration: payload.duration,
          ratio: payload.ratio,
          model_version: payload.model_version,
        },
        (parseQueueDocument($("queueContent").value).segments || []).length + 1,
      );
    }

    function isQueueEditorActive() {
      const active = document.activeElement;
      return active === $("queueContent") || !!active?.closest?.(".queue-item");
    }

    function segmentSummary(segment) {
      const parts = [];
      if (segment.images.length) parts.push(`图片 ${segment.images.length}`);
      if (segment.videos.length) parts.push(`视频 ${segment.videos.length}`);
      if (segment.audios.length) parts.push(`音频 ${segment.audios.length}`);
      if (segment.duration) parts.push(`${segment.duration}s`);
      if (segment.ratio) parts.push(segment.ratio);
      if (segment.model_version) parts.push(segment.model_version);
      return parts.join(" · ") || "仅提示词";
    }

    function renderQueueMediaStrip(segment) {
      const blocks = [];
      if (segment.images.length) {
        const thumbs = segment.images.map((path) => {
          const label = String(path).split("/").pop() || path;
          return `
            <div class="queue-image-thumb" title="${escapeHtml(path)}">
              <img src="/api/file?path=${encodeURIComponent(path)}" alt="${escapeHtml(label)}">
              <span>${escapeHtml(label)}</span>
            </div>
          `;
        }).join("");
        blocks.push(`<div class="queue-image-strip">${thumbs}</div>`);
      }

      const tags = [];
      segment.videos.forEach((path) => {
        const label = String(path).split("/").pop() || path;
        tags.push(`<span class="video" title="${escapeHtml(path)}">视频 · ${escapeHtml(label)}</span>`);
      });
      segment.audios.forEach((path) => {
        const label = String(path).split("/").pop() || path;
        tags.push(`<span class="audio" title="${escapeHtml(path)}">音频 · ${escapeHtml(label)}</span>`);
      });
      if (tags.length) {
        blocks.push(`<div class="queue-media-tags">${tags.join("")}</div>`);
      }

      if (!blocks.length) {
        return "";
      }
      return `<div class="queue-media-strip">${blocks.join("")}</div>`;
    }

    function syncQueueContentFromList() {
      const items = Array.from(document.querySelectorAll(".queue-item"));
      const documentData = {
        version: 1,
        segments: items.map((item, index) => normalizeSegment({
          id: item.dataset.segmentId,
          name: item.querySelector("[data-field='name']").value,
          prompt: item.querySelector("[data-field='prompt']").value,
          images: item.querySelector("[data-field='images']").value,
          videos: item.querySelector("[data-field='videos']").value,
          audios: item.querySelector("[data-field='audios']").value,
          duration: item.querySelector("[data-field='duration']").value,
          ratio: item.querySelector("[data-field='ratio']").value,
          model_version: item.querySelector("[data-field='model_version']").value,
          command: item.querySelector("[data-field='command']").value,
        }, index + 1)),
      };
      $("queueContent").value = queueDocumentToText(documentData);
      queueEditorDirty = true;
      return documentData;
    }

    function renderPromptWithTokens(prompt, segment) {
      if (!prompt) return "";
      const tokens = [];
      const regex = /@(Image|Video|Audio)([^\s@]+)/g;
      let lastIndex = 0;
      let match;

      while ((match = regex.exec(prompt)) !== null) {
        const [fullMatch, type, name] = match;
        const startIndex = match.index;

        if (startIndex > lastIndex) {
          tokens.push({ type: "text", content: prompt.slice(lastIndex, startIndex) });
        }

        tokens.push({ type: "token", tokenType: type.toLowerCase(), name, fullMatch });
        lastIndex = regex.lastIndex;
      }

      if (lastIndex < prompt.length) {
        tokens.push({ type: "text", content: prompt.slice(lastIndex) });
      }

      return tokens.map(token => {
        if (token.type === "text") {
          return escapeHtml(token.content);
        }
        const typeLabel = { image: "图", video: "视", audio: "音" }[token.tokenType] || "?";
        const colorClass = token.tokenType;
        return `<span class="prompt-token ${colorClass}" title="${escapeHtml(token.fullMatch)}">${typeLabel}:${escapeHtml(token.name)}</span>`;
      }).join("");
    }

    function autoResizeTextarea(textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.max(textarea.scrollHeight, 120)}px`;
    }

    function renderQueueList(text) {
      const container = $("queueList");
      const documentData = parseQueueDocument(text);
      const segments = documentData.segments || [];
      container.innerHTML = "";
      if (!segments.length) {
        container.innerHTML = '<div class="hint">当前还没有视频段，点“新增一条”或用上面的表单加入队列。</div>';
        $("queueContent").value = queueDocumentToText(documentData);
        return;
      }

      segments.forEach((segment, index) => {
        const card = document.createElement("div");
        card.className = "queue-item";
        card.dataset.segmentId = segment.id;
        card.innerHTML = `
          <div class="queue-item-head">
            <div>
              <strong>${escapeHtml(segment.name || `片段${index + 1}`)}</strong>
              <div class="hint" style="margin-top:4px;">${escapeHtml(segmentSummary(segment))}</div>
            </div>
            <div class="queue-item-actions">
              <button class="ghost" type="button" data-action="duplicate">复制</button>
              <button class="ghost" type="button" data-action="remove">删除</button>
            </div>
          </div>
          ${renderQueueMediaStrip(segment)}
          <div style="padding:12px;">
            <label>视频段名称</label>
            <input data-field="name" value="${escapeHtml(segment.name)}">
            <label style="margin-top:10px;">提示词</label>
            <textarea class="queue-item-input" data-field="prompt" spellcheck="false">${escapeHtml(segment.prompt)}</textarea>
            <details style="margin-top:10px;">
              <summary style="cursor:pointer;color:var(--accent);font-weight:700;">素材与参数</summary>
              <div style="display:grid;gap:10px;margin-top:10px;">
                <div>
                  <label>图片素材</label>
                  <textarea data-field="images" class="queue-item-input" spellcheck="false">${escapeHtml(segment.images.join("\n"))}</textarea>
                </div>
                <div>
                  <label>视频素材</label>
                  <textarea data-field="videos" class="queue-item-input" spellcheck="false">${escapeHtml(segment.videos.join("\n"))}</textarea>
                </div>
                <div>
                  <label>音频素材</label>
                  <textarea data-field="audios" class="queue-item-input" spellcheck="false">${escapeHtml(segment.audios.join("\n"))}</textarea>
                </div>
                <div class="subgrid">
                  <div>
                    <label>时长</label>
                    <input data-field="duration" value="${escapeHtml(segment.duration)}">
                  </div>
                  <div>
                    <label>比例</label>
                    <input data-field="ratio" value="${escapeHtml(segment.ratio)}">
                  </div>
                  <div>
                    <label>模型</label>
                    <input data-field="model_version" value="${escapeHtml(segment.model_version)}">
                  </div>
                </div>
                <div>
                  <label>原始命令（兼容旧格式时可用）</label>
                  <textarea data-field="command" class="queue-item-input" spellcheck="false">${escapeHtml(segment.command)}</textarea>
                </div>
              </div>
            </details>
          </div>
        `;
        card.querySelectorAll("textarea").forEach(autoResizeTextarea);
        card.querySelectorAll("input, textarea").forEach((field) => {
          field.addEventListener("input", () => {
            if (field.tagName === "TEXTAREA") autoResizeTextarea(field);
            const nameEl = card.querySelector("[data-field='name']");
            const promptEl = card.querySelector("[data-field='prompt']");
            card.querySelector(".queue-item-head strong").textContent = nameEl.value.trim() || `片段${index + 1}`;
            card.querySelector(".queue-item-head .hint").textContent = segmentSummary(normalizeSegment({
              id: card.dataset.segmentId,
              name: nameEl.value,
              prompt: promptEl.value,
              images: card.querySelector("[data-field='images']").value,
              videos: card.querySelector("[data-field='videos']").value,
              audios: card.querySelector("[data-field='audios']").value,
              duration: card.querySelector("[data-field='duration']").value,
              ratio: card.querySelector("[data-field='ratio']").value,
              model_version: card.querySelector("[data-field='model_version']").value,
              command: card.querySelector("[data-field='command']").value,
            }, index + 1));
            syncQueueContentFromList();
          });
          field.addEventListener("change", () => {
            if (["images", "videos", "audios"].includes(field.dataset.field || "")) {
              syncQueueContentFromList();
              renderQueueList($("queueContent").value);
            }
          });
        });
        card.querySelector("[data-action='remove']").addEventListener("click", () => {
          card.remove();
          syncQueueContentFromList();
          renderQueueList($("queueContent").value);
        });
        card.querySelector("[data-action='duplicate']").addEventListener("click", () => {
          const doc = syncQueueContentFromList();
          const current = normalizeSegment(doc.segments[index], doc.segments.length + 1);
          doc.segments.splice(index + 1, 0, { ...current, id: queueItemId(), name: `${current.name}-复制` });
          $("queueContent").value = queueDocumentToText(doc);
          renderQueueList($("queueContent").value);
        });
        container.appendChild(card);
      });
      $("queueContent").value = queueDocumentToText(documentData);
    }

    function snapshotTextareaState(textarea) {
      return {
        start: textarea.selectionStart ?? textarea.value.length,
        end: textarea.selectionEnd ?? textarea.value.length,
        scrollTop: textarea.scrollTop ?? 0,
        scrollLeft: textarea.scrollLeft ?? 0,
        pageX: window.scrollX ?? 0,
        pageY: window.scrollY ?? 0,
      };
    }

    function rememberPromptSelection() {
      promptSelectionSnapshot = snapshotTextareaState($("mmPrompt"));
    }

    function getTextareaState(textarea) {
      if (textarea.id === "mmPrompt" && promptSelectionSnapshot) {
        return promptSelectionSnapshot;
      }
      return snapshotTextareaState(textarea);
    }

    function restoreTextareaState(textarea, state, caretPos) {
      try {
        textarea.focus({ preventScroll: true });
      } catch (_) {
        textarea.focus();
      }
      textarea.setSelectionRange(caretPos, caretPos);
      const scrollTop = state?.scrollTop ?? 0;
      const scrollLeft = state?.scrollLeft ?? 0;
      const pageX = state?.pageX ?? window.scrollX ?? 0;
      const pageY = state?.pageY ?? window.scrollY ?? 0;
      requestAnimationFrame(() => {
        textarea.scrollTop = scrollTop;
        textarea.scrollLeft = scrollLeft;
        window.scrollTo(pageX, pageY);
      });
      if (textarea.id === "mmPrompt") {
        promptSelectionSnapshot = {
          ...state,
          start: caretPos,
          end: caretPos,
          scrollTop,
          scrollLeft,
          pageX,
          pageY,
        };
      }
    }

    function getMaterialRefs() {
      // 只从已上传的素材库生成引用，过滤掉非媒体文件
      const refs = [];
      allMaterials.forEach((mat) => {
        // 过滤掉 .DS_Store 等非媒体文件
        if (mat.name.startsWith('.')) return;

        refs.push({
          token: materialToken(mat),
          path: mat.path,
          cls: mat.kind,
          type: mat.kind,
          name: mat.name,
          stem: materialShortName(mat)
        });
      });
      return refs;
    }

    function insertAtCursor(textarea, text) {
      const state = getTextareaState(textarea);
      const start = state.start ?? textarea.value.length;
      const end = state.end ?? textarea.value.length;
      const before = textarea.value.slice(0, start);
      const after = textarea.value.slice(end);
      const joiner = before && !before.endsWith(" ") && !before.endsWith("\n") ? " " : "";
      textarea.value = `${before}${joiner}${text}${after}`;
      const nextPos = (before + joiner + text).length;
      restoreTextareaState(textarea, state, nextPos);
      updatePreview().catch(() => {});
    }

    function renderRefs() {
      const refList = $("refList");
      refList.innerHTML = "";
      const previewGrid = $("imagePreviewGrid");
      previewGrid.innerHTML = "";
      const refs = getMaterialRefs();

      for (const ref of refs) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `ref-chip ${ref.cls}`.trim();
        btn.textContent = ref.token;
        btn.title = ref.path;
        btn.addEventListener("click", () => insertAtCursor($("mmPrompt"), ref.token));
        refList.appendChild(btn);
      }

      for (const ref of refs.filter(item => item.type === "image")) {
        const card = document.createElement("div");
        card.className = "preview-card";
        card.title = `${ref.token}
${ref.path}`;
        card.innerHTML = `
          <img src="/api/file?path=${encodeURIComponent(ref.path)}" alt="${ref.token}">
          <div class="preview-meta"><strong>${ref.token}</strong><br>${escapeHtml(ref.name || ref.path.split("/").pop() || ref.path)}</div>
        `;
        card.addEventListener("click", () => insertAtCursor($("mmPrompt"), ref.token));
        previewGrid.appendChild(card);
      }

      if (!refs.length) {
        const empty = document.createElement("span");
        empty.className = "hint";
        empty.textContent = "还没有素材引用";
        refList.appendChild(empty);
      }
    }

    function findAtToken(textarea) {
      const state = getTextareaState(textarea);
      const pos = state.start ?? 0;
      const before = textarea.value.slice(0, pos);
      const match = before.match(/(^|\s)(@[^\s@]*)$/);
      if (!match) return null;
      return {
        token: match[2],
        start: pos - match[2].length,
        end: pos
      };
    }

    function hideAutocomplete() {
      $("atAutocomplete").classList.remove("show");
      $("atAutocomplete").innerHTML = "";
    }

    function applyAutocompleteToken(choice) {
      const textarea = $("mmPrompt");
      const info = findAtToken(textarea);
      if (!info) {
        insertAtCursor(textarea, choice.token);
        hideAutocomplete();
        return;
      }
      textarea.value = `${textarea.value.slice(0, info.start)}${choice.token}${textarea.value.slice(info.end)}`;
      const nextPos = info.start + choice.token.length;
      restoreTextareaState(textarea, getTextareaState(textarea), nextPos);
      hideAutocomplete();

      // 自动将素材路径添加到对应的表单字段
      if (choice.path && choice.type) {
        const fieldId = materialFieldId(choice.type);
        if (fieldId) {
          const field = $(fieldId);
          const existing = listFromTextarea(fieldId);
          if (!existing.includes(choice.path)) {
            field.value = field.value ? `${field.value}\n${choice.path}` : choice.path;
          }
        }
      }

      updatePreview().catch(() => {});
    }

    function updateAutocomplete() {
      const box = $("atAutocomplete");
      const textarea = $("mmPrompt");
      const info = findAtToken(textarea);
      if (!info) {
        hideAutocomplete();
        return;
      }
      const keyword = info.token.toLowerCase();
      const matches = getMaterialRefs().filter(item => item.token.toLowerCase().startsWith(keyword));
      if (!matches.length) {
        hideAutocomplete();
        return;
      }
      box.innerHTML = "";
      matches.forEach(item => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "autocomplete-item";
        const thumb = item.type === "image"
          ? `<div class="autocomplete-thumb"><img src="/api/file?path=${encodeURIComponent(item.path)}" alt="${escapeHtml(item.token)}"></div>`
          : `<div class="autocomplete-thumb">${item.type === "video" ? "▶" : "♫"}</div>`;
        btn.innerHTML = `
          ${thumb}
          <div class="autocomplete-copy">
            <strong>${escapeHtml(item.token)}</strong>
            <span>${escapeHtml(item.name || item.path.split("/").pop() || "")}</span>
          </div>
        `;
        btn.addEventListener("mousedown", (event) => event.preventDefault());
        btn.addEventListener("click", () => applyAutocompleteToken(item));
        box.appendChild(btn);
      });
      box.classList.add("show");
    }

    async function updatePreview() {
      const payload = collectMultimodalPayload();
      // Skip API call if no media files
      if (!payload.images.trim() && !payload.videos.trim() && !payload.audios.trim()) {
        $("mmPreview").value = "至少要有一个图片、视频或音频素材。";
        return;
      }
      try {
        const data = await api("/api/build_multimodal", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        $("mmPreview").value = data.command || "";
      } catch (err) {
        $("mmPreview").value = err.message;
      }
    }

    async function addMultimodalTask() {
      const data = await api("/api/build_multimodal", {
        method: "POST",
        body: JSON.stringify(collectMultimodalPayload())
      });
      const doc = parseQueueDocument($("queueContent").value);
      doc.segments.push({
        ...buildQueueSegmentFromForm(),
        command: data.command,
      });
      $("queueContent").value = queueDocumentToText(doc);
      renderQueueList($("queueContent").value);
      $("mmPreview").value = data.command;
      // auto-save so refresh() wont clobber the queue
      const payload = collectPayload();
      payload.queue_content = $("queueContent").value;
      await api("/api/save_queue", { method: "POST", body: JSON.stringify(payload) });
    }

    function clearMultimodalForm() {
      $("mmSegmentName").value = "";
      $("mmPrompt").value = "";
      $("mmImages").value = "";
      $("mmVideos").value = "";
      $("mmAudios").value = "";
      $("mmDuration").value = "5";
      $("mmRatio").value = "9:16";
      $("mmModel").value = "seedance2.0fast";
      $("mmPreview").value = "";
      renderRefs();
      hideAutocomplete();
    }

    function closeMaterialModal() {
      activeMaterial = null;
      $("materialModal").classList.remove("show");
      $("materialModal").setAttribute("aria-hidden", "true");
    }

    function openMaterialModal(mat) {
      activeMaterial = mat;
      $("materialModalTitle").textContent = materialLabel(mat);
      $("materialModalToken").textContent = materialToken(mat);
      $("materialModalPath").textContent = mat.path || "";
      $("materialRenameInput").value = materialShortName(mat);
      $("materialRenameHint").textContent = `保存时会同步修改本地文件名，扩展名 ${mat.name.includes(".") ? "." + mat.name.split(".").pop() : ""} 会保留。`;

      const preview = $("materialModalPreview");
      if (mat.kind === "image") {
        preview.classList.remove("empty");
        preview.innerHTML = `<img src="/api/file?path=${encodeURIComponent(mat.path)}" alt="${escapeHtml(materialLabel(mat))}">`;
      } else {
        preview.classList.add("empty");
        preview.textContent = mat.kind === "video" ? "这里暂时不做视频播放，主要用于改名。" : "这里暂时不做音频播放，主要用于改名。";
      }

      $("materialModal").classList.add("show");
      $("materialModal").setAttribute("aria-hidden", "false");
    }

    function replaceEverywhere(oldValue, nextValue) {
      if (!oldValue || oldValue === nextValue) return;
      ["mmPrompt", "mmImages", "mmVideos", "mmAudios"].forEach((id) => {
        const el = $(id);
        if (el.value.includes(oldValue)) {
          el.value = el.value.split(oldValue).join(nextValue);
        }
      });
    }

    function applyRenamedMaterial(oldMaterial, newMaterial) {
      allMaterials = allMaterials.map((item) => item.path === oldMaterial.path ? newMaterial : item);
      replaceEverywhere(oldMaterial.path, newMaterial.path);
      replaceEverywhere(materialToken(oldMaterial), materialToken(newMaterial));
      renderMaterials();
      renderRefs();
      updateAutocomplete();
      updatePreview().catch(() => {});
    }

    async function saveMaterialRename() {
      if (!activeMaterial) return;
      const input = $("materialRenameInput").value.trim();
      const data = await api("/api/rename_upload", {
        method: "POST",
        body: JSON.stringify({
          path: activeMaterial.path,
          new_name: input
        })
      });
      applyRenamedMaterial(activeMaterial, data.material);
      openMaterialModal(data.material);
    }

    async function uploadBlobs(kind, files, textareaId) {
      const form = new FormData();
      form.append("kind", kind);
      for (const file of files) {
        form.append("files", file);
      }
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "上传失败");
      }
      appendLines($(textareaId), data.paths || []);
      await loadMaterials();
      renderRefs();
      updateAutocomplete();
      return data;
    }

    async function handlePasteImage(event) {
      const items = Array.from(event.clipboardData?.items || []);
      const files = items
        .filter(item => item.type && item.type.startsWith("image/"))
        .map(item => item.getAsFile())
        .filter(Boolean);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      $("pasteImageZone").classList.add("active");
      try {
        await uploadBlobs("image", files, "mmImages");
      } catch (err) {
        alert(err.message);
      } finally {
        setTimeout(() => $("pasteImageZone").classList.remove("active"), 300);
      }
    }

    async function saveQueue() {
      syncQueueContentFromList();
      await api("/api/save_queue", {
        method: "POST",
        body: JSON.stringify(collectPayload())
      });
      await refresh();
      alert("队列已保存");
    }

    async function startQueue() {
      syncQueueContentFromList();
      await api("/api/start", {
        method: "POST",
        body: JSON.stringify(collectPayload())
      });
      await refresh();
    }

    async function stopQueue() {
      await api("/api/stop", {
        method: "POST",
        body: JSON.stringify({})
      });
      await refresh();
    }

    async function detectDreamina() {
      const data = await api("/api/status");
      if (!data.detected_dreamina) {
        throw new Error("没有自动检测到 dreamina。你可能还没安装即梦 CLI。");
      }
      $("dreamina").value = data.detected_dreamina;
      await api("/api/save_config", {
        method: "POST",
        body: JSON.stringify({
          dreamina: data.detected_dreamina,
          queue_file: $("queueFile").value.trim(),
          output_root: $("outputRoot").value.trim(),
          state_file: $("stateFile").value.trim(),
          poll_interval: Number($("pollInterval").value || 30),
          timeout_seconds: Number($("timeoutSeconds").value || 10800),
          resume: $("resume").checked,
          stop_on_failure: $("stopOnFailure").checked
        })
      });
      alert(`已检测到 dreamina：\n${data.detected_dreamina}`);
    }

    $("detectBtn").addEventListener("click", () => detectDreamina().catch(err => alert(err.message)));
    $("saveBtn").addEventListener("click", () => saveQueue().catch(err => alert(err.message)));
    $("startBtn").addEventListener("click", () => startQueue().catch(err => alert(err.message)));
    $("stopBtn").addEventListener("click", () => stopQueue().catch(err => alert(err.message)));
    $("refreshBtn").addEventListener("click", () => refresh().catch(err => alert(err.message)));
    $("uploadImagesBtn").addEventListener("click", () => uploadFiles("image", "uploadImages", "mmImages").catch(err => alert(err.message)));
    $("uploadVideosBtn").addEventListener("click", () => uploadFiles("video", "uploadVideos", "mmVideos").catch(err => alert(err.message)));
    $("uploadAudiosBtn").addEventListener("click", () => uploadFiles("audio", "uploadAudios", "mmAudios").catch(err => alert(err.message)));
    $("addMultimodalBtn").addEventListener("click", () => addMultimodalTask().catch(err => alert(err.message)));
    $("addQueueItemBtn").addEventListener("click", () => {
      const doc = parseQueueDocument($("queueContent").value);
      doc.segments.push(normalizeSegment({ id: queueItemId(), name: `片段${doc.segments.length + 1}` }, doc.segments.length + 1));
      $("queueContent").value = queueDocumentToText(doc);
      renderQueueList($("queueContent").value);
    });
    $("clearMultimodalBtn").addEventListener("click", clearMultimodalForm);
    $("pasteImageZone").addEventListener("paste", handlePasteImage);
    $("pasteImageZone").addEventListener("click", () => $("pasteImageZone").focus());
    $("materialModalCloseBtn").addEventListener("click", closeMaterialModal);
    $("materialInsertBtn").addEventListener("click", () => {
      if (activeMaterial) {
        insertMaterialRef(activeMaterial);
      }
    });
    $("materialRenameBtn").addEventListener("click", () => saveMaterialRename().catch(err => alert(err.message)));
    $("materialModal").addEventListener("click", (event) => {
      if (event.target === $("materialModal")) {
        closeMaterialModal();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideAutocomplete();
        closeMaterialModal();
      }
    });
    $("mmPrompt").addEventListener("keyup", updateAutocomplete);
    $("mmPrompt").addEventListener("click", updateAutocomplete);
    $("mmPrompt").addEventListener("blur", () => setTimeout(hideAutocomplete, 120));
    ["keyup", "click", "input", "select", "scroll"].forEach((eventName) => {
      $("mmPrompt").addEventListener(eventName, rememberPromptSelection);
    });
    $("queueContent").addEventListener("input", () => {
      if (document.activeElement === $("queueContent")) {
        renderQueueList($("queueContent").value);
      }
    });
    ["mmPrompt", "mmDuration", "mmRatio", "mmModel", "mmImages", "mmVideos", "mmAudios"].forEach((id) => {
      $(id).addEventListener("input", () => {
        renderRefs();
        updatePreview().catch(() => {});
        if (id === "mmPrompt") updateAutocomplete();
      });
    });

    refresh().catch(err => alert(err.message));
    renderQueueList($("queueContent").value);
    renderRefs();
    updatePreview().catch(() => {});
    setInterval(() => refresh().catch(() => {}), 5000);

    async function loadMaterials() {
      try {
        const res = await api('/api/uploads_list');
        allMaterials = res.uploads || [];
        renderMaterials();
        renderRefs();
        updateAutocomplete();
      } catch (err) {
        console.error('loadMaterials error:', err);
      }
    }

    window.showMaterialTab = function(tab) {
      currentMaterialTab = tab;
      updateMaterialTabStyle();
      renderMaterials();
    };

    function updateMaterialTabStyle() {
      document.querySelectorAll('#materialTabs button').forEach(function(btn) {
        var tab = btn.id.replace('tab', '').toLowerCase();
        var active = tab === currentMaterialTab;
        btn.style.fontWeight = active ? '700' : 'normal';
        btn.style.background = active ? 'rgba(31,107,94,0.18)' : 'rgba(31,107,94,0.08)';
      });
    }

    function insertMaterialRef(mat) {
      var token = materialToken(mat);
      var textarea = $('mmPrompt');
      var state = getTextareaState(textarea);
      var pos = state.start != null ? state.start : textarea.value.length;
      var before = textarea.value.slice(0, pos);
      var after = textarea.value.slice(pos);
      var joiner = (before && before[before.length-1] !== ' ' && before[before.length-1] !== '\n') ? ' ' : '';
      textarea.value = before + joiner + token + after;
      var nextPos = (before + joiner + token).length;
      restoreTextareaState(textarea, state, nextPos);
      var fieldId = materialFieldId(mat.kind);
      if (fieldId) {
        var existing = listFromTextarea(fieldId);
        if (!existing.includes(mat.path)) {
          var field = $(fieldId);
          field.value = field.value ? field.value + '\n' + mat.path : mat.path;
        }
      }
      updatePreview().catch(function() {});
      renderRefs();
    }

    function renderMaterials() {
      var grid = $('materialGrid');
      var clean = allMaterials.filter(function(m) { return m && m.name && !m.name.startsWith('.'); });
      var filtered = currentMaterialTab === 'all'
        ? clean
        : clean.filter(function(m) { return m.kind === currentMaterialTab; });
      if (!filtered.length) {
        grid.innerHTML = '<span class="hint">暂无素材，上传后会显示在这。</span>';
        return;
      }
      grid.innerHTML = '';
      filtered.forEach(function(mat) {
        var card = document.createElement('div');
        card.className = 'preview-card';
        var shortName = materialShortName(mat);
        var token = materialToken(mat);
        var media = document.createElement('div');
        if (mat.kind === 'image') {
          media.innerHTML = '<img src="/api/file?path=' + encodeURIComponent(mat.path) + '" alt="">';
        } else {
          var icon = mat.kind === 'video' ? '&#9654;' : '&#9834;';
          var kindColor = mat.kind === 'video' ? 'rgba(215,109,63,0.10)' : 'rgba(109,101,88,0.12)';
          media.innerHTML = '<div style="height:110px;display:flex;align-items:center;justify-content:center;background:' + kindColor + ';font-size:36px;color:var(--muted);">' + icon + '</div>';
        }
        media.addEventListener('click', function() { openMaterialModal(mat); });
        card.appendChild(media);

        var meta = document.createElement('div');
        meta.className = 'preview-meta';
        meta.style.fontSize = '11px';
        meta.innerHTML =
          '<strong style="color:' + (mat.kind === 'image' ? 'var(--accent)' : 'var(--accent-2)') + ';">' + escapeHtml(token) + '</strong><br>' +
          '<span style="color:var(--muted);">' + escapeHtml(shortName) + '</span>';
        card.appendChild(meta);

        var actions = document.createElement('div');
        actions.className = 'material-actions';

        var insertBtn = document.createElement('button');
        insertBtn.type = 'button';
        insertBtn.className = 'ghost';
        insertBtn.textContent = '插入 @';
        insertBtn.addEventListener('click', function(event) {
          event.stopPropagation();
          insertMaterialRef(mat);
        });
        actions.appendChild(insertBtn);

        var editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'ghost';
        editBtn.textContent = '预览/改名';
        editBtn.addEventListener('click', function(event) {
          event.stopPropagation();
          openMaterialModal(mat);
        });
        actions.appendChild(editBtn);

        card.appendChild(actions);
        card.title = mat.path;
        grid.appendChild(card);
      });
    }

    loadMaterials().catch(function() {});
    setInterval(function() { loadMaterials().catch(function() {}); }, 10000);

  