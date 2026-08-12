package com.personalworkbench.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.Manifest;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.JavascriptInterface;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.net.URI;
import java.net.URISyntaxException;

public class MainActivity extends Activity {
    private static final String PREFS = "workbench_connection";
    private static final String SERVER_URL = "server_url";
    private static final int FILE_CHOOSER_REQUEST = 4102;
    private static final int NOTIFICATION_PERMISSION_REQUEST = 4103;
    private static final String NOTIFICATION_CHANNEL = "workbench_updates_v2";
    private static final String[] BILIBILI_PACKAGES = {
        "tv.danmaku.bili",
        "tv.danmaku.bilibilihd"
    };
    private static final String[] DOUYIN_PACKAGES = {
        "com.ss.android.ugc.aweme",
        "com.ss.android.ugc.aweme.lite"
    };

    private WebView webView;
    private FrameLayout activityRoot;
    private LinearLayout appContent;
    private FrameLayout fullscreenContainer;
    private View fullscreenView;
    private WebChromeClient.CustomViewCallback fullscreenCallback;
    private ProgressBar progress;
    private Button backButton;
    private LinearLayout errorPanel;
    private TextView errorTitle;
    private TextView errorDetail;
    private SharedPreferences preferences;
    private ValueCallback<Uri[]> uploadCallback;
    private Uri pendingCameraUri;
    private boolean mainFrameFailed;
    private boolean webCanGoBack;
    private long lastExitBackPressedAt;
    private String lastConsoleError = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        prepareNotifications();
        buildInterface();
        String savedUrl = preferences.getString(SERVER_URL, "");
        if (isSafeServerUrl(savedUrl)) {
            loadWorkbench(savedUrl);
        } else {
            webView.loadUrl("file:///android_asset/welcome.html");
            webView.postDelayed(() -> showConnectionDialog(false), 350);
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void prepareNotifications() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                NOTIFICATION_CHANNEL,
                "AI Agent 处理进度",
                NotificationManager.IMPORTANCE_HIGH
            );
            channel.setDescription("健康分析、学习计划和工作台任务完成提醒");
            channel.enableVibration(true);
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(channel);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION_REQUEST);
        }
    }

    private class NotificationBridge {
        @JavascriptInterface
        public void showNotification(String title, String body) {
            runOnUiThread(() -> {
                if (!isWorkbenchUrl(Uri.parse(webView.getUrl() == null ? "" : webView.getUrl()))) return;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                    && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    return;
                }
                Intent openApp = new Intent(MainActivity.this, MainActivity.class);
                openApp.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                PendingIntent pendingIntent = PendingIntent.getActivity(
                    MainActivity.this,
                    0,
                    openApp,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
                );
                String safeTitle = title == null || title.isEmpty() ? "AI Agent 个人工作台" : title;
                String safeBody = body == null || body.isEmpty() ? "打开工作台查看更新" : body;
                Notification notification = new Notification.Builder(MainActivity.this, NOTIFICATION_CHANNEL)
                    .setSmallIcon(android.R.drawable.stat_notify_more)
                    .setContentTitle(safeTitle)
                    .setContentText(safeBody)
                    .setStyle(new Notification.BigTextStyle().bigText(safeBody))
                    .setContentIntent(pendingIntent)
                    .setAutoCancel(true)
                    .setCategory(Notification.CATEGORY_STATUS)
                    .setPriority(Notification.PRIORITY_HIGH)
                    .setVisibility(Notification.VISIBILITY_PRIVATE)
                    .build();
                NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
                manager.notify((int) (System.currentTimeMillis() & 0x7fffffff), notification);
            });
        }

        @JavascriptInterface
        public void openExternalLink(String value) {
            runOnUiThread(() -> {
                String currentUrl = webView.getUrl();
                if (currentUrl == null || !isWorkbenchUrl(Uri.parse(currentUrl))) return;
                Uri uri = Uri.parse(value == null ? "" : value.trim());
                String scheme = uri.getScheme();
                if ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) {
                    openExternalHttpUrl(uri);
                } else if (scheme != null && !scheme.isEmpty()) {
                    openExternalUrl(uri);
                }
            });
        }

        @JavascriptInterface
        public void setCanGoBack(boolean value) {
            runOnUiThread(() -> {
                webCanGoBack = value;
                updateBackButton();
            });
        }
    }

    private void buildInterface() {
        activityRoot = new FrameLayout(this);
        appContent = new LinearLayout(this);
        appContent.setOrientation(LinearLayout.VERTICAL);
        appContent.setBackgroundColor(Color.rgb(255, 253, 252));
        activityRoot.addView(appContent, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        fullscreenContainer = new FrameLayout(this);
        fullscreenContainer.setBackgroundColor(Color.BLACK);
        fullscreenContainer.setVisibility(View.GONE);
        activityRoot.addView(fullscreenContainer, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(17), 0, dp(10), 0);
        toolbar.setBackgroundColor(Color.rgb(25, 71, 55));
        appContent.addView(toolbar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));
        appContent.setOnApplyWindowInsetsListener((view, insets) -> {
            int statusBarHeight = insets.getSystemWindowInsetTop();
            toolbar.setPadding(dp(17), statusBarHeight, dp(10), 0);
            ViewGroup.LayoutParams params = toolbar.getLayoutParams();
            params.height = dp(52) + statusBarHeight;
            toolbar.setLayoutParams(params);
            return insets;
        });

        backButton = new Button(this);
        backButton.setText("‹");
        backButton.setContentDescription("返回上一页");
        backButton.setTextColor(Color.WHITE);
        backButton.setTextSize(26);
        backButton.setAllCaps(false);
        backButton.setPadding(0, 0, 0, dp(2));
        backButton.setBackgroundColor(Color.TRANSPARENT);
        backButton.setVisibility(View.GONE);
        backButton.setOnClickListener(view -> handleBackNavigation());
        toolbar.addView(backButton, new LinearLayout.LayoutParams(dp(42), dp(44)));

        TextView title = new TextView(this);
        title.setText("AI Agent 个人工作台");
        title.setTextColor(Color.WHITE);
        title.setTextSize(17);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        Button settings = new Button(this);
        settings.setText("连接设置");
        settings.setTextColor(Color.WHITE);
        settings.setTextSize(12);
        settings.setAllCaps(false);
        settings.setBackgroundColor(Color.TRANSPARENT);
        settings.setOnClickListener(view -> showConnectionDialog(true));
        toolbar.addView(settings, new LinearLayout.LayoutParams(dp(88), dp(44)));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        progress.setVisibility(View.GONE);
        appContent.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(2)));

        FrameLayout content = new FrameLayout(this);
        appContent.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        webView = new WebView(this);
        content.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        errorPanel = createErrorPanel();
        errorPanel.setVisibility(View.GONE);
        content.addView(errorPanel, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(activityRoot);

        WebSettings webSettings = webView.getSettings();
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        webSettings.setDatabaseEnabled(true);
        webSettings.setAllowFileAccess(false);
        webSettings.setAllowContentAccess(true);
        webSettings.setMediaPlaybackRequiresUserGesture(false);
        webSettings.setBuiltInZoomControls(false);
        webSettings.setDisplayZoomControls(false);
        webSettings.setSupportZoom(false);
        webSettings.setUseWideViewPort(true);
        webSettings.setLoadWithOverviewMode(true);
        webSettings.setTextZoom(100);
        webSettings.setCacheMode(WebSettings.LOAD_DEFAULT);
        webSettings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webSettings.setSafeBrowsingEnabled(true);
        webSettings.setUserAgentString(webSettings.getUserAgentString() + " PersonalWorkbenchAndroid/0.3.0");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        webView.addJavascriptInterface(new NotificationBridge(), "PersonalWorkbenchAndroid");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                mainFrameFailed = false;
                lastConsoleError = "";
                hideLoadError();
                progress.setVisibility(View.VISIBLE);
                updateBackButton();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
                updateBackButton();
                if (!mainFrameFailed && isWorkbenchUrl(Uri.parse(url))) {
                    view.postDelayed(() -> verifyPageStarted(view, url), 1400);
                }
            }

            @Override
            public void doUpdateVisitedHistory(WebView view, String url, boolean isReload) {
                super.doUpdateVisitedHistory(view, url, isReload);
                updateBackButton();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                Uri uri = request.getUrl();
                String scheme = uri.getScheme();
                if ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) {
                    if (isWorkbenchUrl(uri)) return false;
                    openExternalHttpUrl(uri);
                    return true;
                }
                openExternalUrl(uri);
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    if (!isWorkbenchUrl(request.getUrl())) {
                        progress.setVisibility(View.GONE);
                        fallbackExternalPage(request.getUrl(), "站内加载失败，已尝试使用系统应用打开");
                        return;
                    }
                    mainFrameFailed = true;
                    String reason = describeNetworkError(error.getErrorCode());
                    showLoadError(
                        "没有连接到云端工作台",
                        reason + "\n\n错误代码：" + error.getErrorCode() + " · " + error.getDescription()
                    );
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame()) {
                    if (!isWorkbenchUrl(request.getUrl())) {
                        progress.setVisibility(View.GONE);
                        if (response.getStatusCode() >= 400) {
                            fallbackExternalPage(request.getUrl(), "原平台限制了站内访问，已尝试使用系统应用打开");
                        }
                        return;
                    }
                    mainFrameFailed = true;
                    showLoadError(
                        "工作台返回了异常状态",
                        "服务器已响应，但网页没有正常打开。HTTP 状态码：" + response.getStatusCode()
                    );
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, android.net.http.SslError error) {
                handler.cancel();
                Uri failedUri = Uri.parse(error.getUrl());
                if (!isWorkbenchUrl(failedUri)) {
                    progress.setVisibility(View.GONE);
                    if (view.canGoBack()) view.goBack();
                    Toast.makeText(MainActivity.this, "原平台的安全证书异常，已停止加载", Toast.LENGTH_SHORT).show();
                    return;
                }
                mainFrameFailed = true;
                showLoadError(
                    "HTTPS 证书验证失败",
                    "为了保护你的数据，APP 已停止加载。请确认手机日期时间正确，且工作台使用有效 HTTPS 证书。证书错误：" + error.getPrimaryError()
                );
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onShowCustomView(View view, CustomViewCallback callback) {
                showFullscreenVideo(view, callback);
            }

            @Override
            public void onHideCustomView() {
                hideFullscreenVideo();
            }

            @Override
            public boolean onConsoleMessage(ConsoleMessage message) {
                if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    lastConsoleError = message.message() + "（第 " + message.lineNumber() + " 行）";
                }
                return super.onConsoleMessage(message);
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (uploadCallback != null) uploadCallback.onReceiveValue(null);
                uploadCallback = callback;
                openImageChooser();
                return true;
            }
        });

        webView.setDownloadListener(createDownloadListener());
    }

    private void showFullscreenVideo(View view, WebChromeClient.CustomViewCallback callback) {
        if (fullscreenView != null) {
            callback.onCustomViewHidden();
            return;
        }
        fullscreenView = view;
        fullscreenCallback = callback;
        fullscreenContainer.addView(view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        fullscreenContainer.setVisibility(View.VISIBLE);
        appContent.setVisibility(View.GONE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        );
    }

    private void hideFullscreenVideo() {
        if (fullscreenView == null) return;
        fullscreenContainer.removeView(fullscreenView);
        fullscreenContainer.setVisibility(View.GONE);
        fullscreenView = null;
        appContent.setVisibility(View.VISIBLE);
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
        if (fullscreenCallback != null) {
            fullscreenCallback.onCustomViewHidden();
            fullscreenCallback = null;
        }
    }

    private LinearLayout createErrorPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER_HORIZONTAL);
        panel.setPadding(dp(28), dp(46), dp(28), dp(24));
        panel.setBackgroundColor(Color.rgb(251, 250, 247));

        errorTitle = new TextView(this);
        errorTitle.setTextColor(Color.rgb(25, 71, 55));
        errorTitle.setTextSize(22);
        errorTitle.setTypeface(null, android.graphics.Typeface.BOLD);
        errorTitle.setGravity(Gravity.CENTER);
        panel.addView(errorTitle, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        errorDetail = new TextView(this);
        errorDetail.setTextColor(Color.rgb(74, 78, 72));
        errorDetail.setTextSize(15);
        errorDetail.setGravity(Gravity.CENTER);
        errorDetail.setLineSpacing(0, 1.25f);
        LinearLayout.LayoutParams detailParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        detailParams.setMargins(0, dp(18), 0, dp(26));
        panel.addView(errorDetail, detailParams);

        Button retry = createPanelButton("重新连接", true);
        retry.setOnClickListener(view -> loadWorkbench(preferences.getString(SERVER_URL, "")));
        panel.addView(retry, panelButtonParams());

        Button openBrowser = createPanelButton("在手机浏览器中测试", false);
        openBrowser.setOnClickListener(view -> openSavedUrlInBrowser());
        panel.addView(openBrowser, panelButtonParams());

        Button connection = createPanelButton("修改连接地址", false);
        connection.setOnClickListener(view -> showConnectionDialog(true));
        panel.addView(connection, panelButtonParams());
        return panel;
    }

    private Button createPanelButton(String label, boolean primary) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setTextColor(primary ? Color.WHITE : Color.rgb(25, 71, 55));
        button.setBackgroundColor(primary ? Color.rgb(25, 71, 55) : Color.rgb(235, 239, 234));
        return button;
    }

    private LinearLayout.LayoutParams panelButtonParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        params.setMargins(0, 0, 0, dp(10));
        return params;
    }

    private void loadWorkbench(String value) {
        String url = normalizeUrl(value);
        if (!isSafeServerUrl(url)) {
            showConnectionDialog(false);
            return;
        }
        hideLoadError();
        progress.setVisibility(View.VISIBLE);
        webView.loadUrl(url);
    }

    private void hideLoadError() {
        if (errorPanel != null) errorPanel.setVisibility(View.GONE);
        if (webView != null) webView.setVisibility(View.VISIBLE);
        updateBackButton();
    }

    private void showLoadError(String title, String detail) {
        progress.setVisibility(View.GONE);
        webView.setVisibility(View.INVISIBLE);
        errorTitle.setText(title);
        errorDetail.setText(detail);
        errorPanel.setVisibility(View.VISIBLE);
        updateBackButton();
    }

    private void verifyPageStarted(WebView view, String loadedUrl) {
        if (mainFrameFailed || !loadedUrl.equals(view.getUrl()) || !isWorkbenchUrl(Uri.parse(loadedUrl))) return;
        String probe = "(function(){try{var root=document.getElementById('root');return !!(root&&root.children&&root.children.length);}catch(e){return false;}})();";
        view.evaluateJavascript(probe, result -> {
            if ("false".equals(result) || "null".equals(result)) {
                String detail = "网页已经到达手机，但页面脚本没有启动。请先更新手机的 Android System WebView 或 Chrome，然后重试。";
                if (!lastConsoleError.isEmpty()) detail += "\n\n脚本信息：" + lastConsoleError;
                showLoadError("页面没有正常启动", detail);
            }
        });
    }

    private String describeNetworkError(int code) {
        if (code == WebViewClient.ERROR_HOST_LOOKUP) {
            return "手机无法解析工作台域名。请检查网络连接，并确认输入的云端地址正确。";
        }
        if (code == WebViewClient.ERROR_CONNECT || code == WebViewClient.ERROR_TIMEOUT) {
            return "找到了地址，但云端工作台暂时没有响应。请稍后重试。";
        }
        if (code == WebViewClient.ERROR_FAILED_SSL_HANDSHAKE) {
            return "HTTPS 安全连接没有建立。请确认手机日期时间正确。";
        }
        return "请确认手机网络可用，并重新检查工作台 HTTPS 地址。";
    }

    private void openSavedUrlInBrowser() {
        String url = preferences.getString(SERVER_URL, "");
        if (!isSafeServerUrl(url)) {
            showConnectionDialog(true);
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
            Toast.makeText(this, "没有找到可用的浏览器", Toast.LENGTH_SHORT).show();
        }
    }

    private void openExternalUrl(Uri uri) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, uri);
            intent.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(intent);
        } catch (Exception ignored) {
            Toast.makeText(this, "无法打开这个链接", Toast.LENGTH_SHORT).show();
        }
    }

    private void openExternalHttpUrl(Uri uri) {
        if (isPlatformHost(uri, "bilibili.com", "b23.tv")) {
            if (openInInstalledApp(uri, BILIBILI_PACKAGES, "已在哔哩哔哩中打开")) return;
            if (launchInstalledAppWithCopiedLink(uri, BILIBILI_PACKAGES, "哔哩哔哩")) return;
            openExternalUrl(uri);
            return;
        }
        if (isPlatformHost(uri, "douyin.com", "iesdouyin.com")) {
            String videoId = extractDouyinVideoId(uri);
            if (!videoId.isEmpty()) {
                Uri deepLink = Uri.parse("snssdk1128://aweme/detail/" + videoId);
                if (openInInstalledApp(deepLink, DOUYIN_PACKAGES, "已打开抖音作品")) return;
            }
            if (openInInstalledApp(uri, DOUYIN_PACKAGES, "已在抖音中打开")) return;
            if (launchInstalledAppWithCopiedLink(uri, DOUYIN_PACKAGES, "抖音")) return;
            openExternalUrl(uri);
            return;
        }
        openExternalUrl(uri);
    }

    private boolean openInInstalledApp(Uri uri, String[] packageNames, String successMessage) {
        for (String packageName : packageNames) {
            try {
                Intent intent = new Intent(Intent.ACTION_VIEW, uri);
                intent.setPackage(packageName);
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                if (intent.resolveActivity(getPackageManager()) == null) continue;
                startActivity(intent);
                Toast.makeText(this, successMessage, Toast.LENGTH_SHORT).show();
                return true;
            } catch (Exception ignored) {
                // Try the next known package, then fall back to the in-app WebView.
            }
        }
        return false;
    }

    private boolean launchInstalledAppWithCopiedLink(Uri uri, String[] packageNames, String appName) {
        for (String packageName : packageNames) {
            Intent launchIntent = getPackageManager().getLaunchIntentForPackage(packageName);
            if (launchIntent == null) continue;
            try {
                ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                clipboard.setPrimaryClip(ClipData.newPlainText(appName + "作品链接", uri.toString()));
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                startActivity(launchIntent);
                Toast.makeText(this, "已打开" + appName + "，作品链接已复制", Toast.LENGTH_SHORT).show();
                return true;
            } catch (Exception ignored) {
                // Try the next package before falling back to the browser.
            }
        }
        return false;
    }

    private String extractDouyinVideoId(Uri uri) {
        String path = uri.getPath();
        if (path != null) {
            java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("/(?:video|discover)/(\\d{8,})", java.util.regex.Pattern.CASE_INSENSITIVE).matcher(path);
            if (matcher.find()) return matcher.group(1);
        }
        String vid = uri.getQueryParameter("vid");
        return vid != null && vid.matches("\\d{8,}") ? vid : "";
    }

    private void fallbackExternalPage(Uri uri, String message) {
        webView.stopLoading();
        if (webView.canGoBack()) webView.goBack();
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
        openExternalUrl(uri);
    }

    private boolean isPlatformHost(Uri uri, String... domains) {
        String host = uri.getHost();
        if (host == null) return false;
        String normalizedHost = host.toLowerCase(java.util.Locale.ROOT);
        for (String domain : domains) {
            if (normalizedHost.equals(domain) || normalizedHost.endsWith("." + domain)) return true;
        }
        return false;
    }

    private void updateBackButton() {
        if (backButton == null) return;
        backButton.setVisibility(webView != null && (webCanGoBack || webView.canGoBack()) ? View.VISIBLE : View.GONE);
    }

    private void handleBackNavigation() {
        if (fullscreenView != null) {
            hideFullscreenVideo();
            return;
        }
        if (webView == null) {
            finishAfterBackConfirmation();
            return;
        }
        String currentUrl = webView.getUrl();
        if (currentUrl != null && isWorkbenchUrl(Uri.parse(currentUrl))) {
            webView.evaluateJavascript(
                "(function(){try{return Boolean(window.__personalWorkbenchHandleBack&&window.__personalWorkbenchHandleBack());}catch(error){return false;}})()",
                value -> {
                    if ("true".equals(value)) {
                        hideLoadError();
                        return;
                    }
                    navigateWebViewOrExit();
                }
            );
            return;
        }
        navigateWebViewOrExit();
    }

    private void navigateWebViewOrExit() {
        if (webView != null && webView.canGoBack()) {
            hideLoadError();
            webView.goBack();
            return;
        }
        finishAfterBackConfirmation();
    }

    private void finishAfterBackConfirmation() {
        long now = System.currentTimeMillis();
        if (now - lastExitBackPressedAt > 2200) {
            lastExitBackPressedAt = now;
            Toast.makeText(this, "再按一次返回键退出 AI Agent 个人工作台", Toast.LENGTH_SHORT).show();
            return;
        }
        CookieManager.getInstance().flush();
        super.onBackPressed();
    }

    private void showConnectionDialog(boolean allowCancel) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(preferences.getString(SERVER_URL, ""));
        input.setHint("https://你的工作台域名");
        input.setSelectAllOnFocus(true);
        int pad = dp(20);
        LinearLayout wrap = new LinearLayout(this);
        wrap.setPadding(pad, dp(6), pad, 0);
        wrap.addView(input, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        AlertDialog dialog = new AlertDialog.Builder(this)
            .setTitle("连接云端工作台")
            .setMessage("粘贴工作台的 HTTPS 地址。登录后只会显示当前账号自己的数据；地址只保存在这台手机。")
            .setView(wrap)
            .setPositiveButton("连接", null)
            .setNegativeButton(allowCancel ? "取消" : "稍后设置", null)
            .create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String url = normalizeUrl(input.getText().toString());
            if (!isSafeServerUrl(url)) {
                input.setError("请输入完整有效的 https:// 工作台地址");
                return;
            }
            preferences.edit().putString(SERVER_URL, url).apply();
            dialog.dismiss();
            loadWorkbench(url);
        }));
        dialog.show();
    }

    private String normalizeUrl(String value) {
        String normalized = value == null ? "" : value.trim();
        while (normalized.endsWith("/")) normalized = normalized.substring(0, normalized.length() - 1);
        return normalized;
    }

    private boolean isSafeServerUrl(String value) {
        if (value == null || value.isEmpty()) return false;
        try {
            URI uri = new URI(value);
            String host = uri.getHost();
            return "https".equalsIgnoreCase(uri.getScheme())
                && host != null
                && !host.trim().isEmpty()
                && uri.getUserInfo() == null;
        } catch (URISyntaxException ignored) {
            return false;
        }
    }

    private boolean isWorkbenchUrl(Uri candidate) {
        String configuredValue = preferences == null ? "" : preferences.getString(SERVER_URL, "");
        if (!isSafeServerUrl(configuredValue) || candidate == null) return false;
        try {
            URI configured = new URI(normalizeUrl(configuredValue));
            String candidateScheme = candidate.getScheme();
            String candidateHost = candidate.getHost();
            if (candidateScheme == null || candidateHost == null) return false;
            int configuredPort = configured.getPort() == -1 ? 443 : configured.getPort();
            int candidatePort = candidate.getPort() == -1 ? 443 : candidate.getPort();
            return configured.getScheme().equalsIgnoreCase(candidateScheme)
                && configured.getHost().equalsIgnoreCase(candidateHost)
                && configuredPort == candidatePort;
        } catch (URISyntaxException ignored) {
            return false;
        }
    }

    private void openImageChooser() {
        Intent picker = new Intent(Intent.ACTION_GET_CONTENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("image/*");
        picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);

        Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, "workbench-" + System.currentTimeMillis() + ".jpg");
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
        pendingCameraUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
        if (pendingCameraUri != null) {
            camera.putExtra(MediaStore.EXTRA_OUTPUT, pendingCameraUri);
            camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        }

        Intent chooser = Intent.createChooser(picker, "选择图片或拍照");
        if (camera.resolveActivity(getPackageManager()) != null && pendingCameraUri != null) {
            chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{camera});
        }
        startActivityForResult(chooser, FILE_CHOOSER_REQUEST);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST || uploadCallback == null) return;
        Uri[] result = null;
        if (resultCode == RESULT_OK) {
            if (data == null || data.getData() == null) {
                if (pendingCameraUri != null) result = new Uri[]{pendingCameraUri};
            } else if (data.getClipData() != null) {
                ClipData clip = data.getClipData();
                result = new Uri[clip.getItemCount()];
                for (int index = 0; index < clip.getItemCount(); index++) result[index] = clip.getItemAt(index).getUri();
            } else {
                result = new Uri[]{data.getData()};
            }
        } else if (pendingCameraUri != null) {
            getContentResolver().delete(pendingCameraUri, null, null);
        }
        uploadCallback.onReceiveValue(result);
        uploadCallback = null;
        pendingCameraUri = null;
    }

    private DownloadListener createDownloadListener() {
        return (url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                request.setMimeType(mimeType);
                request.addRequestHeader("User-Agent", userAgent);
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) request.addRequestHeader("Cookie", cookie);
                String filename = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType);
                request.setTitle(filename);
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
                DownloadManager manager = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                manager.enqueue(request);
                Toast.makeText(this, "已开始下载", Toast.LENGTH_SHORT).show();
            } catch (Exception error) {
                Toast.makeText(this, "下载失败，请稍后重试", Toast.LENGTH_SHORT).show();
            }
        };
    }

    @Override
    public void onBackPressed() {
        handleBackNavigation();
    }

    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        hideFullscreenVideo();
        if (uploadCallback != null) uploadCallback.onReceiveValue(null);
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
