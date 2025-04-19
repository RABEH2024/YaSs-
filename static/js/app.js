// ==================================================
// =========== FILE 3: FRONTEND JAVASCRIPT ==========
// ==================================================
document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const messagesContainer = document.getElementById('messages');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const modelSelect = document.getElementById('model-select');
    const temperatureSlider = document.getElementById('temperature-slider');
    const temperatureValue = document.getElementById('temperature-value');
    const maxTokensInput = document.getElementById('max-tokens-input');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const ttsToggle = document.getElementById('tts-toggle');
    const sidebar = document.getElementById('settings-sidebar');
    const toggleSidebarButtonDesktop = document.getElementById('toggle-sidebar-desktop');
    const mobileSettingsButton = document.getElementById('mobile-settings-button');
    const conversationsList = document.getElementById('conversations-list');
    const newConversationButton = document.getElementById('new-conversation');
    const offlineIndicator = document.getElementById('offline-indicator');
    const micButton = document.getElementById('mic-button');
    const stopMicButton = document.getElementById('stop-mic-button');
    const confirmModal = document.getElementById('confirm-modal');
    const confirmMessage = document.getElementById('confirm-message');
    const confirmOkButton = document.getElementById('confirm-ok');
    const confirmCancelButton = document.getElementById('confirm-cancel');

    // --- State ---
    let currentConversationId = null;
    let isLoading = false;
    let isTTSEnabled = true;
    let isDarkMode = true;
    let currentModel = 'google/gemini-1.5-flash'; // Default model
    let currentTemperature = 0.7;
    let currentMaxTokens = 512;
    let conversationToDelete = null;
    let messageHistory = []; // لتخزين الرسائل الحالية في الواجهة للسياق

    // --- Web Speech API ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = SpeechRecognition ? new SpeechRecognition() : null;
    let isListening = false;
    let synthesis = window.speechSynthesis;
    let voices = [];
    let arabicVoice = null;
    let isSpeaking = false;
    let currentUtterance = null;

    // --- Initialization ---
    function initializeApp() {
        loadSettings();
        updateDarkMode();
        loadConversations(); // تحميل المحادثات أولاً
        setupEventListeners();
        setupSpeechRecognition();
        loadVoices();
        checkOnlineStatus();
        if (messageInput) messageInput.focus();

        // تحميل آخر محادثة أو بدء محادثة جديدة
        const lastConvId = localStorage.getItem('yasmin_last_conversation_id');
        if (lastConvId) {
            loadConversation(lastConvId);
        } else {
            startNewConversation(); // يبدأ بمحادثة فارغة ورسالة ترحيب
        }
        adjustInputHeight(); // ضبط ارتفاع الإدخال الأولي
    }

    // --- Settings ---
    function loadSettings() {
        isDarkMode = localStorage.getItem('yasmin_dark_mode') !== 'false';
        isTTSEnabled = localStorage.getItem('yasmin_tts_enabled') !== 'false';
        currentModel = localStorage.getItem('yasmin_model') || 'google/gemini-1.5-flash';
        currentTemperature = parseFloat(localStorage.getItem('yasmin_temperature') || '0.7');
        currentMaxTokens = parseInt(localStorage.getItem('yasmin_max_tokens') || '512', 10);

        if (darkModeToggle) darkModeToggle.checked = isDarkMode;
        if (ttsToggle) ttsToggle.checked = isTTSEnabled;
        if (modelSelect) modelSelect.value = currentModel; // قد يحتاج لتحميل النماذج أولاً
        if (temperatureSlider) temperatureSlider.value = currentTemperature;
        if (temperatureValue) temperatureValue.textContent = currentTemperature.toFixed(1);
        if (maxTokensInput) maxTokensInput.value = currentMaxTokens;
    }

    function saveSetting(key, value) { localStorage.setItem(`yasmin_${key}`, value); }
    function updateDarkMode() { document.body.classList.toggle('dark-mode', isDarkMode); }

    // --- Conversation Management ---
    async function loadConversations() {
        try {
            const response = await fetch('/api/conversations');
            if (!response.ok) throw new Error('Failed to fetch conversations');
            const data = await response.json();
            renderConversations(data.conversations || []);
        } catch (error) {
            console.error("Error loading conversations:", error);
            if (conversationsList) conversationsList.innerHTML = '<div class="empty-state">فشل تحميل المحادثات</div>';
        }
    }

    function renderConversations(conversations) {
        if (!conversationsList) return;
        conversationsList.innerHTML = '';
        if (conversations.length === 0) {
            conversationsList.innerHTML = '<div class="empty-state">لا توجد محادثات</div>';
            return;
        }
        conversations.forEach(conv => {
            const item = document.createElement('div');
            item.classList.add('conversation-item');
            item.dataset.id = conv.id;
            if (conv.id === currentConversationId) item.classList.add('active');

            const titleSpan = document.createElement('span');
            titleSpan.textContent = conv.title || 'محادثة بدون عنوان';
            item.appendChild(titleSpan);

            const actionsDiv = document.createElement('div');
            actionsDiv.classList.add('conversation-actions');
            const deleteButton = document.createElement('button');
            deleteButton.classList.add('icon-button', 'delete-conv-btn');
            deleteButton.title = 'حذف المحادثة';
            deleteButton.innerHTML = '<i class="fas fa-trash-alt fa-xs"></i>'; // تصغير الأيقونة
            deleteButton.onclick = (e) => { e.stopPropagation(); showConfirmModal(conv.id, conv.title); };
            actionsDiv.appendChild(deleteButton);
            item.appendChild(actionsDiv);

            item.onclick = () => loadConversation(conv.id);
            conversationsList.appendChild(item);
        });
    }

    async function loadConversation(id) {
        if (isLoading || id === currentConversationId) return;
        console.log(`Loading conversation: ${id}`);
        setLoadingState(true, "جاري تحميل المحادثة...");
        try {
            const response = await fetch(`/api/conversations/${id}`);
            if (!response.ok) {
                 if (response.status === 404) { console.warn(`Conv ${id} not found.`); startNewConversation(); return; }
                 throw new Error(`Failed: ${response.status}`);
            }
            const data = await response.json();
            currentConversationId = id;
            saveSetting('last_conversation_id', id);
            clearMessages();
            messageHistory = []; // مسح السجل المؤقت
            (data.messages || []).forEach(msg => {
                addMessageToUI(msg.role, msg.content, msg.id);
                // إضافة الرسائل المحملة للسجل المؤقت
                messageHistory.push({ role: msg.role, content: msg.content });
            });
            updateActiveConversationUI();
            scrollToBottom(true);
        } catch (error) {
            console.error("Error loading conversation:", error);
            showError("فشل تحميل المحادثة.");
            startNewConversation();
        } finally { setLoadingState(false); }
    }

    function startNewConversation() {
        console.log("Starting new conversation");
        if (isSpeaking) cancelSpeech(); // أوقف النطق عند بدء محادثة جديدة
        currentConversationId = null;
        saveSetting('last_conversation_id', '');
        clearMessages();
        messageHistory = []; // مسح السجل المؤقت
        addWelcomeMessage();
        updateActiveConversationUI();
        if (messageInput) messageInput.focus();
    }

    function updateActiveConversationUI() {
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.toggle('active', item.dataset.id === currentConversationId);
        });
    }

    function showConfirmModal(id, title) {
        conversationToDelete = id;
        if (confirmMessage) confirmMessage.textContent = `هل أنت متأكد من حذف محادثة "${title || 'بدون عنوان'}"؟`;
        if (confirmModal) confirmModal.style.display = 'flex';
    }

    function hideConfirmModal() {
        conversationToDelete = null;
        if (confirmModal) confirmModal.style.display = 'none';
    }

    async function deleteConversation() {
        if (!conversationToDelete) return;
        const idToDelete = conversationToDelete;
        hideConfirmModal();
        setLoadingState(true, "جاري الحذف...");
        try {
            const response = await fetch(`/api/conversations/${idToDelete}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('Failed to delete');
            await response.json();
            if (idToDelete === currentConversationId) startNewConversation();
            loadConversations();
            showSuccess("تم حذف المحادثة.");
        } catch (error) { console.error("Error deleting:", error); showError("فشل حذف المحادثة."); }
        finally { setLoadingState(false); }
    }

    // --- Message Handling ---
    function clearMessages() { if (messagesContainer) messagesContainer.innerHTML = ''; }
    function addWelcomeMessage() { addMessageToUI('assistant', 'مرحباً! أنا ياسمين، مساعدتك الذكية. كيف يمكنني مساعدتك اليوم؟', `ai-welcome-${Date.now()}`); }

    function addMessageToUI(role, text, messageId = `msg-${Date.now()}`) {
        if (!messagesContainer) return;
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble', role === 'user' ? 'user-bubble' : (role === 'error' ? 'error-bubble' : 'ai-bubble'));
        bubble.dataset.id = messageId;

        const contentP = document.createElement('p');
        // استبدال ```language ... ``` بـ <pre><code class="language-...">...</code></pre>
        // واستبدال `code` بـ <code>...</code>
        let formattedText = text.replace(/```(\w+)?\n([\s\S]*?)\n```/g, (match, lang, code) => {
            const languageClass = lang ? `language-${lang}` : '';
            // يجب تنظيف الكود من HTML قبل وضعه في pre/code
            const escapedCode = code.replace(/</g, "<").replace(/>/g, ">");
            return `<pre><code class="${languageClass}">${escapedCode}</code></pre>`;
        });
        formattedText = formattedText.replace(/`([^`]+)`/g, '<code>$1</code>');
        // تحويل الأسطر الجديدة خارج بلوكات الكود
        contentP.innerHTML = formattedText.split('<pre>').map((part, index) => {
            if (index === 0) return part.replace(/\n/g, '<br>');
            const [codeBlock, rest] = part.split('</pre>');
            return `<pre>${codeBlock}</pre>${rest.replace(/\n/g, '<br>')}`;
        }).join('');

        bubble.appendChild(contentP);

        if (role === 'ai' || role === 'error') {
            const actions = document.createElement('div');
            actions.classList.add('message-actions');
            const copyBtn = document.createElement('button');
            copyBtn.classList.add('copy-btn'); copyBtn.title = 'نسخ'; copyBtn.innerHTML = '<i class="fas fa-copy fa-xs"></i>';
            copyBtn.onclick = () => copyToClipboard(text); actions.appendChild(copyBtn);
            if (role === 'ai') {
                // زر إعادة التوليد غير مدعوم حاليًا بشكل كامل في الواجهة الخلفية
                // const regenBtn = document.createElement('button');
                // regenBtn.classList.add('regen-btn'); regenBtn.title = 'إعادة توليد الرد'; regenBtn.innerHTML = '<i class="fas fa-sync-alt fa-xs"></i>';
                // regenBtn.onclick = () => regenerateResponse(messageId); actions.appendChild(regenBtn);
                if (synthesisSupported) {
                    const speakBtn = document.createElement('button');
                    speakBtn.classList.add('speak-btn'); speakBtn.title = 'استماع'; speakBtn.innerHTML = '<i class="fas fa-volume-up fa-xs"></i>';
                    speakBtn.onclick = () => speakText(text); actions.appendChild(speakBtn);
                }
            }
            bubble.appendChild(actions);
        }
        messagesContainer.appendChild(bubble);
        scrollToBottom();
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text)
            .then(() => showSuccess('تم النسخ!'))
            .catch(err => { console.error('Copy failed: ', err); showError('فشل النسخ.'); });
    }

    // --- API Interaction ---
    async function handleSendMessage() {
        const messageText = messageInput.value.trim();
        if (!messageText || isLoading || isListening) return; // منع الإرسال أثناء الاستماع أيضًا

        const messageId = `user-${Date.now()}`;
        addMessageToUI('user', messageText, messageId);
        messageHistory.push({ role: 'user', content: messageText }); // إضافة للسجل المؤقت
        messageInput.value = '';
        adjustInputHeight();
        setLoadingState(true);
        setLastError(null);
        if (isSpeaking) cancelSpeech();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    // إرسال السجل المؤقت بالكامل (بما في ذلك رسالة المستخدم الأخيرة)
                    history: messageHistory.slice(-10), // آخر 10 رسائل للسياق
                    model: currentModel,
                    temperature: currentTemperature,
                    max_tokens: currentMaxTokens,
                    conversation_id: currentConversationId
                }),
            });

            const data = await response.json();

            if (!response.ok || data.error) {
                // عرض خطأ API كرسالة خطأ في الدردشة
                throw new Error(data.error || `فشل طلب الـ API: ${response.status}`);
            }

            // تحديث ID المحادثة إذا كانت جديدة
            if (data.conversation_id && !currentConversationId) {
                 currentConversationId = data.conversation_id;
                 saveSetting('last_conversation_id', currentConversationId);
                 loadConversations(); // تحديث القائمة
            }

            const aiMessageId = `ai-${Date.now()}`;
            addMessageToUI('assistant', data.reply, aiMessageId);
            messageHistory.push({ role: 'assistant', content: data.reply }); // إضافة رد AI للسجل المؤقت
            if (isTTSEnabled) {
                speakText(data.reply);
            }
            checkOnlineStatus(true);

        } catch (error) {
            console.error("Error sending message:", error);
            const errorMessage = `فشل الاتصال بالمساعد: ${error.message}`;
            addMessageToUI('error', errorMessage, `error-${Date.now()}`);
            checkOnlineStatus(false);
        } finally {
            setLoadingState(false);
        }
    }

    // --- UI Updates ---
    function setLoadingState(loading, statusText = "جاري الكتابة...") {
        isLoading = loading;
        if (sendButton) {
            sendButton.disabled = loading;
            sendButton.innerHTML = loading ? '<div class="spinner"></div>' : '<i class="fas fa-paper-plane"></i>';
        }
        if (messageInput) messageInput.disabled = loading || isListening;
        if (micButton) micButton.disabled = loading || isListening;
        if (stopMicButton) stopMicButton.disabled = loading; // يمكن إيقاف الميكروفون أثناء التحميل
    }

    function scrollToBottom(instant = false) {
        if (messagesContainer) {
            messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: instant ? 'auto' : 'smooth' });
        }
    }

    function adjustInputHeight() {
        if (messageInput) {
            messageInput.style.height = 'auto';
            const scrollHeight = messageInput.scrollHeight;
            const maxHeight = 120; // زيادة الارتفاع الأقصى قليلاً
            messageInput.style.height = `${Math.min(scrollHeight, maxHeight)}px`;
            messageInput.style.overflowY = scrollHeight > maxHeight ? 'auto' : 'hidden';
        }
    }

    function showError(message) { console.error("Error:", message); setLastError(message); setTimeout(() => setLastError(null), 5000); }
    function showSuccess(message) { console.info("Success:", message); /* يمكن إضافة إشعار مؤقت */ }
    function setLastError(message) {
        // يمكنك تحسين عرض الخطأ هنا
        if (message) alert(`خطأ: ${message}`); // استخدام alert مؤقتًا
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        if (sendButton) sendButton.onclick = handleSendMessage;
        if (messageInput) {
            messageInput.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); } };
            messageInput.oninput = adjustInputHeight;
        }
        if (darkModeToggle) darkModeToggle.onchange = () => { isDarkMode = darkModeToggle.checked; saveSetting('dark_mode', isDarkMode); updateDarkMode(); };
        if (ttsToggle) ttsToggle.onchange = () => { isTTSEnabled = ttsToggle.checked; saveSetting('tts_enabled', isTTSEnabled); if (!isTTSEnabled && isSpeaking) cancelSpeech(); };
        if (modelSelect) modelSelect.onchange = () => { currentModel = modelSelect.value; saveSetting('model', currentModel); };
        if (temperatureSlider) temperatureSlider.oninput = () => { currentTemperature = parseFloat(temperatureSlider.value); if (temperatureValue) temperatureValue.textContent = currentTemperature.toFixed(1); saveSetting('temperature', currentTemperature); };
        if (maxTokensInput) maxTokensInput.onchange = () => { currentMaxTokens = parseInt(maxTokensInput.value, 10); saveSetting('max_tokens', currentMaxTokens); };
        if (toggleSidebarButtonDesktop) toggleSidebarButtonDesktop.onclick = toggleSidebar;
        if (mobileSettingsButton) mobileSettingsButton.onclick = toggleSidebar;
        if (newConversationButton) newConversationButton.onclick = startNewConversation;
        if (confirmCancelButton) confirmCancelButton.onclick = hideConfirmModal;
        if (confirmOkButton) confirmOkButton.onclick = deleteConversation;
        if (confirmModal) confirmModal.onclick = (e) => { if (e.target === confirmModal) hideConfirmModal(); };
        if (micButton) micButton.onclick = startListening;
        if (stopMicButton) stopMicButton.onclick = stopListening;
        window.addEventListener('online', () => checkOnlineStatus(true));
        window.addEventListener('offline', () => checkOnlineStatus(false));
    }

    function toggleSidebar() {
        if (sidebar) {
            sidebar.classList.toggle('sidebar-collapsed');
            const icon = toggleSidebarButtonDesktop?.querySelector('i');
            if (icon) {
                icon.classList.toggle('fa-chevron-left');
                icon.classList.toggle('fa-chevron-right');
            }
            // إخفاء/إظهار المحتوى بناءً على حالة الطي
            const isCollapsed = sidebar.classList.contains('sidebar-collapsed');
            document.querySelectorAll('#settings-sidebar > *:not(.sidebar-header), .sidebar-section h3 span, .setting-item, .primary-button span, .sidebar-footer span, .social-links')
                .forEach(el => el.style.display = isCollapsed ? 'none' : '');
             if(isCollapsed) {
                 document.querySelectorAll('.sidebar-section h3').forEach(h3 => h3.style.justifyContent = 'center');
                 document.querySelector('.sidebar-header h2 .sidebar-title').style.display = 'none';
                 document.querySelector('.sidebar-header').style.paddingBottom = '0';
             } else {
                 document.querySelectorAll('.sidebar-section h3').forEach(h3 => h3.style.justifyContent = '');
                 document.querySelector('.sidebar-header h2 .sidebar-title').style.display = '';
                 document.querySelector('.sidebar-header').style.paddingBottom = '';
             }
        }
    }

    // --- Speech Recognition ---
    function setupSpeechRecognition() {
        if (!recognition) {
            console.warn("Web Speech Recognition not supported.");
            if (micButton) { micButton.disabled = true; micButton.title = "التعرف على الصوت غير مدعوم"; }
            if (stopMicButton) stopMicButton.style.display = 'none';
            return;
        }
        recognition.lang = 'ar-SA'; recognition.continuous = false; recognition.interimResults = false;
        recognition.onstart = () => { isListening = true; if (micButton) micButton.style.display = 'none'; if (stopMicButton) stopMicButton.style.display = 'flex'; console.log("STT started"); };
        recognition.onend = () => { isListening = false; if (micButton) micButton.style.display = 'flex'; if (stopMicButton) stopMicButton.style.display = 'none'; console.log("STT ended"); };
        recognition.onerror = (event) => {
            console.error("STT error:", event.error);
            let errorMsg = `خطأ STT: ${event.error}`;
            if (event.error === 'no-speech') errorMsg = "لم يتم اكتشاف كلام.";
            else if (event.error === 'not-allowed') errorMsg = "تم رفض إذن الميكروفون.";
            showError(errorMsg); isListening = false;
            if (micButton) micButton.style.display = 'flex'; if (stopMicButton) stopMicButton.style.display = 'none';
        };
        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            console.log("Transcript:", transcript);
            if (messageInput) { messageInput.value = transcript; adjustInputHeight(); handleSendMessage(); }
        };
    }
    function startListening() {
        if (!recognitionSupported || isListening || isLoading) return;
        try { if (isSpeaking) cancelSpeech(); recognition.start(); }
        catch (e) { console.error("STT start failed:", e); showError("فشل بدء التعرف على الصوت."); }
    }
    function stopListening() { if (recognitionSupported && isListening) recognition.stop(); }

    // --- Text-to-Speech ---
    function loadVoices() {
        if (!synthesis) return;
        const getAndSetVoices = () => {
            voices = synthesis.getVoices();
            if (voices.length > 0) {
                arabicVoice = voices.find(v => v.lang.startsWith('ar') && v.name.includes('Female')) || voices.find(v => v.lang.startsWith('ar')) || null;
                console.log("Selected TTS voice:", arabicVoice ? arabicVoice.name : "Default");
                synthesis.onvoiceschanged = null; // Remove listener once loaded
            }
        };
        getAndSetVoices();
        if (voices.length === 0 && synthesis.onvoiceschanged !== undefined) {
            synthesis.onvoiceschanged = getAndSetVoices;
        }
    }
    function speakText(text) {
        if (!isTTSEnabled || !synthesis || !text) return;
        cancelSpeech();
        currentUtterance = new SpeechSynthesisUtterance(text);
        if (arabicVoice) { currentUtterance.voice = arabicVoice; currentUtterance.lang = arabicVoice.lang; }
        else { currentUtterance.lang = 'ar-SA'; }
        currentUtterance.rate = 1.0; currentUtterance.pitch = 1.0;
        currentUtterance.onstart = () => { isSpeaking = true; /* Update UI if needed */ };
        currentUtterance.onend = () => { isSpeaking = false; currentUtterance = null; };
        currentUtterance.onerror = (e) => { console.error("TTS error:", e.error); isSpeaking = false; currentUtterance = null; showError(`خطأ نطق: ${e.error}`); };
        synthesis.speak(currentUtterance);
    }
    function cancelSpeech() { if (isSpeaking && synthesis) synthesis.cancel(); isSpeaking = false; currentUtterance = null; }

    // --- Online/Offline Status ---
    function checkOnlineStatus(isOnline = navigator.onLine) {
        if (offlineIndicator) offlineIndicator.classList.toggle('visible', !isOnline);
        console.log("Network status:", isOnline ? "Online" : "Offline");
    }

    // --- Run ---
    initializeApp();
});
// ==================================================
// ============ END OF FILE 3 =======================
// ==================================================
