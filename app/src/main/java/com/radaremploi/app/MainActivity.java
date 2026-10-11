package com.radaremploi.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import org.json.JSONObject;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.TimeUnit;

public class MainActivity extends Activity {
  private static final String HOST = "appassets.androidplatform.net";
  static final String PREFS = "alertes";
  static final String WORK = "alertes-offres";
  private WebView web;

  @Override
  protected void onCreate(Bundle state) {
    super.onCreate(state);
    web = new WebView(this);
    setContentView(web);
    WebSettings s = web.getSettings();
    s.setJavaScriptEnabled(true);
    s.setDomStorageEnabled(true);
    s.setAllowFileAccess(false);
    s.setAllowContentAccess(false);
    s.setTextZoom(100);

    final WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
        .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
        .build();

    web.setWebViewClient(new WebViewClient() {
      @Override
      public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        return loader.shouldInterceptRequest(request.getUrl());
      }
      @Override
      public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        Uri u = request.getUrl();
        if (HOST.equals(u.getHost())) return false;
        try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (ActivityNotFoundException e) { /* aucune appli */ }
        return true;
      }
    });

    web.addJavascriptInterface(new Bridge(), "Android");
    watchFeed();
    if (state != null) web.restoreState(state);
    else web.loadUrl("https://" + HOST + "/assets/www/index.html");
  }

  /** Vérifie la liste d'offres en arrière-plan et demande le droit d'afficher des notifications. */
  private void watchFeed() {
    Constraints net = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(FeedWorker.class, 3, TimeUnit.HOURS)
        .setConstraints(net)
        .build();
    WorkManager.getInstance(getApplicationContext())
        .enqueueUniquePeriodicWork("flux-offres", ExistingPeriodicWorkPolicy.KEEP, req);
    if (Build.VERSION.SDK_INT >= 33
        && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
      requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 7);
    }
  }

  @Override
  protected void onSaveInstanceState(Bundle out) {
    super.onSaveInstanceState(out);
    web.saveState(out);
  }

  @Override
  public void onBackPressed() {
    if (web.canGoBack()) web.goBack();
    else super.onBackPressed();
  }

  private class Bridge {
    /** Requête HTTPS faite hors de la page, pour ne pas dépendre des règles du navigateur. */
    @JavascriptInterface
    public void http(final String id, final String method, final String url, final String headersJson, final String body) {
      new Thread(() -> {
        Net.Reply r;
        try {
          Map<String, String> headers = new HashMap<>();
          JSONObject h = new JSONObject(headersJson == null || headersJson.isEmpty() ? "{}" : headersJson);
          Iterator<String> it = h.keys();
          while (it.hasNext()) { String k = it.next(); headers.put(k, h.getString(k)); }
          r = Net.call(method, url, headers, body);
        } catch (Exception e) {
          r = new Net.Reply(0, String.valueOf(e.getMessage()));
        }
        final String js = "window.__http&&window.__http(" + JSONObject.quote(id) + "," + r.status + "," + JSONObject.quote(r.body) + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
      }).start();
    }

    /** Active (config JSON) ou coupe (chaîne vide) la vérification quotidienne des nouvelles offres. */
    @JavascriptInterface
    public void setAlerts(final String config) {
      final Context app = getApplicationContext();
      final boolean on = config != null && !config.isEmpty();
      app.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("config", on ? config : "").apply();
      if (!on) {
        WorkManager.getInstance(app).cancelUniqueWork(WORK);
        return;
      }
      Constraints net = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
      PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(AlertWorker.class, 24, TimeUnit.HOURS)
          .setConstraints(net)
          .build();
      WorkManager.getInstance(app).enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.UPDATE, req);
      runOnUiThread(() -> {
        if (Build.VERSION.SDK_INT >= 33
            && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
          requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 7);
        }
      });
    }

    @JavascriptInterface
    public boolean alertsOn() {
      String c = getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("config", "");
      return c != null && !c.isEmpty();
    }
  }
}
