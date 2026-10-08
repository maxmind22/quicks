document.addEventListener('DOMContentLoaded', () => {
    const submitBtn = document.getElementById('submit');
    const inputField = document.getElementById('search-input') || document.querySelector('.form-control');
    const resultsContainer = document.querySelector('.results');

    if (!submitBtn || !inputField || !resultsContainer) {
        return;
    }

    submitBtn.addEventListener('click', sendQuery);

    function updateBadge(queriesToday, maxQueries) {
        if (queriesToday !== undefined) {
            const badge = document.getElementById('daily-queries-badge');
            if (badge) {
                badge.textContent = `${queriesToday} / ${maxQueries}`;
                if (queriesToday >= maxQueries) {
                    badge.className = 'badge bg-danger';
                }
            }
        }
    }

    async function sendQuery(e) {
        e.preventDefault();
        
        const queryText = inputField.value.trim();
        if (!queryText) return;

        // 1. Create and append User Message bubble
        const userBubble = document.createElement("div");
        userBubble.classList.add("chat-message-right", "pb-4");
        userBubble.innerHTML = `
            <div class="chat-bubble chat-bubble-user">
                <div class="chat-bubble-author text-end mb-1">You</div>
                <div class="chat-bubble-text">${escapeHtml(queryText)}</div>
            </div>
        `;
        resultsContainer.appendChild(userBubble);
        
        // Clear input and scroll to bottom
        inputField.value = "";
        submitBtn.disabled = true;
        scrollToBottom();

        // 2. Create and append Bot bubble with initial typing indicator
        const botBubble = document.createElement("div");
        botBubble.classList.add("chat-message-left", "pb-4");
        botBubble.innerHTML = `
            <div class="chat-bubble chat-bubble-ai">
                <div class="chat-bubble-author mb-1"><i class="fa-solid fa-robot me-1"></i>Quicks AI</div>
                <div class="chat-bubble-text text-stream-content">
                    <span class="spinner-border spinner-border-sm me-2 text-primary" role="status" aria-hidden="true"></span>
                    <span>Searching documents & thinking...</span>
                </div>
            </div>
        `;
        resultsContainer.appendChild(botBubble);
        scrollToBottom();

        const streamContentEl = botBubble.querySelector('.text-stream-content');
        let fullAnswer = "";
        let hasStartedStreaming = false;

        const formData = new FormData();
        formData.append('query', queryText);

        try {
            // Attempt ultra-fast SSE streaming first (< 1.8s TTFB)
            const response = await fetch('/search/stream', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                let errorMsg = "Something went wrong. Please try again.";
                try {
                    const errData = await response.json();
                    if (errData.error) errorMsg = errData.error;
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || "";

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(trimmed.slice(6));
                            if (data.token) {
                                if (!hasStartedStreaming) {
                                    hasStartedStreaming = true;
                                    streamContentEl.innerHTML = "";
                                }
                                fullAnswer += data.token;
                                streamContentEl.innerHTML = escapeHtml(fullAnswer).replace(/\n/g, '<br>');
                                scrollToBottom();
                            }
                            if (data.done) {
                                updateBadge(data.queries_today, data.max_queries);
                            }
                            if (data.error) {
                                throw new Error(data.error);
                            }
                        } catch (err) {
                            if (err.message && !err.message.includes('JSON')) {
                                throw err;
                            }
                        }
                    }
                }
            }

            if (!hasStartedStreaming && !fullAnswer) {
                throw new Error("No answer generated from documents.");
            }

        } catch (streamError) {
            console.warn("Streaming unavailable or interrupted, falling back to /search:", streamError);
            
            try {
                const fallbackResp = await fetch('/search', {
                    method: 'POST',
                    body: formData
                });
                const fallbackData = await fallbackResp.json();

                if (!fallbackResp.ok || fallbackData.error) {
                    throw new Error(fallbackData.error || "Unable to search documents.");
                }

                const answerText = fallbackData.answer || JSON.stringify(fallbackData);
                streamContentEl.innerHTML = escapeHtml(answerText).replace(/\n/g, '<br>');
                updateBadge(fallbackData.queries_today, fallbackData.max_queries);
                scrollToBottom();
            } catch (fallbackError) {
                botBubble.innerHTML = `
                    <div class="chat-bubble chat-bubble-danger">
                        <div class="chat-bubble-author mb-1"><i class="fa-solid fa-triangle-exclamation me-1"></i>System Error</div>
                        <div class="chat-bubble-text">${escapeHtml(fallbackError.message || streamError.message)}</div>
                    </div>
                `;
                scrollToBottom();
            }
        } finally {
            submitBtn.disabled = false;
        }
    }

    function scrollToBottom() {
        resultsContainer.scrollTop = resultsContainer.scrollHeight;
    }

    function escapeHtml(text) {
        if (!text) return "";
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    
    // Initial scroll to bottom
    scrollToBottom();
});
