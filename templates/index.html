<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <!-- استخدام متغير العنوان من Flask -->
    <title>{{ app_title }}</title>
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" integrity="sha512-DTOQO9RWCH3ppGqcWaEA1BIZOC6xxalwEsw9c2QQeAIftl+Vegovlnee1c9QX4TctnWMn13TZye+giMm8e2LwA==" crossorigin="anonymous" referrerpolicy="no-referrer" />
    <!-- Google Font (Cairo) -->
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
    <!-- Link to CSS (using Flask's url_for) -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}">
    <!-- Favicon (optional) -->
    <!-- <link rel="icon" href="{{ url_for('static', filename='favicon.ico') }}"> -->
</head>
<body class="dark-mode"> <!-- البدء بالوضع الداكن افتراضيًا -->

    <div class="app-container">
        <!-- Sidebar -->
        <aside id="settings-sidebar" class="sidebar-collapsed">
            <div class="sidebar-header">
                <h2><i class="fas fa-robot sidebar-icon-title"></i><span class="sidebar-title">{{ app_title }}</span></h2>
                <button id="toggle-sidebar-desktop" class="icon-button toggle-sidebar-btn" title="فتح/إغلاق الإعدادات">
                    <i class="fas fa-chevron-left"></i>
                </button>
            </div>

            <button id="new-conversation" class="primary-button">
                <i class="fas fa-plus"></i> <span>محادثة جديدة</span>
            </button>

            <div class="sidebar-section conversations-section">
                <h3><i class="fas fa-comments sidebar-icon"></i><span>المحادثات</span></h3>
                <div id="conversations-list" class="conversations-container scrollable">
                    <div class="empty-state">لا توجد محادثات سابقة</div>
                    <!-- Conversation items added here by JS -->
                </div>
            </div>

            <div class="sidebar-section settings-section">
                <h3><i class="fas fa-cog sidebar-icon"></i><span>الإعدادات</span></h3>
                <div class="setting-item">
                    <label for="model-select">النموذج:</label>
                    <select id="model-select" class="setting-input">
                        <!-- Models loaded dynamically by JS -->
                         <option value="google/gemini-1.5-flash">Gemini 1.5 Flash (أسرع)</option>
                         <option value="mistralai/Mistral-7B-Instruct-v0.1">Mistral 7B Instruct</option>
                         <option value="google/gemma-7b-it">Gemma 7B IT</option>
                         <option value="meta-llama/Meta-Llama-3-8B-Instruct">LLaMA 3 8B Instruct</option>
                         <option value="openai/gpt-3.5-turbo">GPT-3.5 Turbo (OpenRouter)</option>
                         <option value="anthropic/claude-3-haiku">Claude 3 Haiku (OpenRouter)</option>
                    </select>
                    <small class="setting-hint">اختر نموذج الذكاء الاصطناعي.</small>
                </div>
                <div class="setting-item">
                    <label for="temperature-slider">درجة الإبداع (Temperature):</label>
                    <div class="slider-container">
                        <input type="range" id="temperature-slider" min="0" max="1" step="0.1" value="0.7">
                        <span id="temperature-value">0.7</span>
                    </div>
                     <small class="setting-hint">قيمة أعلى = ردود أكثر إبداعًا.</small>
                </div>
                 <div class="setting-item toggle-item">
                    <label for="tts-toggle">قراءة الردود صوتياً:</label>
                    <label class="switch">
                        <input type="checkbox" id="tts-toggle" checked>
                        <span class="slider round"></span>
                    </label>
                </div>
                <div class="setting-item toggle-item">
                    <label for="dark-mode-toggle">الوضع الليلي:</label>
                    <label class="switch">
                        <input type="checkbox" id="dark-mode-toggle" checked>
                        <span class="slider round"></span>
                    </label>
                </div>
            </div>

            <div class="sidebar-footer">
                <span class="app-version">الإصدار 1.3.0</span>
                 <!-- Social Links -->
                <div class="social-links">
                    <a href="#" target="_blank" rel="noopener noreferrer" title="فيسبوك" class="icon-button"><i class="fab fa-facebook-f"></i></a>
                    <a href="#" target="_blank" rel="noopener noreferrer" title="منصة إكس" class="icon-button"><i class="fab fa-twitter"></i></a>
                    <a href="#" target="_blank" rel="noopener noreferrer" title="يوتيوب" class="icon-button"><i class="fab fa-youtube"></i></a>
                </div>
            </div>
        </aside>

        <!-- Main Chat Area -->
        <main id="chat-container">
            <div id="offline-indicator">
                <i class="fas fa-exclamation-triangle"></i>
                <span>أنت غير متصل بالإنترنت. الردود ستكون محدودة.</span>
            </div>
            <div id="messages" class="scrollable">
                <!-- Messages will be dynamically added here by JS -->
            </div>
            <div id="input-area">
                <div id="input-wrapper">
                     <button id="mic-button" class="icon-button input-icon-button" title="تحدث (قد لا يكون مدعومًا)">
                        <i class="fas fa-microphone"></i>
                    </button>
                     <button id="stop-mic-button" class="icon-button input-icon-button mic-active" title="إيقاف التسجيل" style="display: none;">
                        <i class="fas fa-stop-circle"></i>
                    </button>
                    <textarea id="message-input" placeholder="اكتب رسالتك هنا..." rows="1"></textarea>
                    <button id="send-button" class="icon-button input-icon-button" title="إرسال">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </div>
                 <div class="input-footer">
                    <span class="typing-hint">Enter للإرسال • Shift+Enter لسطر جديد</span>
                    <button id="mobile-settings-button" class="icon-button mobile-only" title="الإعدادات">
                        <i class="fas fa-bars"></i> <!-- تغيير الأيقونة لتبدو كقائمة -->
                    </button>
                </div>
            </div>
        </main>
    </div>

    <!-- Confirmation Modal -->
    <div id="confirm-modal" class="modal">
        <div class="modal-content">
            <h3>تأكيد الحذف</h3>
            <p id="confirm-message">هل أنت متأكد من حذف هذه المحادثة؟</p>
            <div class="modal-buttons">
                <button id="confirm-cancel" class="secondary-button">إلغاء</button>
                <button id="confirm-ok" class="danger-button">حذف</button>
            </div>
        </div>
    </div>

    <!-- JavaScript (using Flask's url_for) -->
    <script src="{{ url_for('static', filename='js/app.js') }}"></script>
</body>
</html>
