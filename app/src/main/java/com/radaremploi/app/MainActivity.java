package com.radaremploi.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.core.content.FileProvider;
import androidx.webkit.WebViewAssetLoader;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import org.json.JSONObject;

import java.io.File;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.TimeUnit;

public class MainActivity extends Activity {
  private static final String HOST = "appassets.androidplatform.net";
  static final String PREFS = "alertes";
  static final String WORK = "alertes-offres";
  private static final String FILES = "com.radaremploi.app.fichiers";
  private static final int PICK = 41;
  private WebView web;
  /** Message à montrer quand la page sera prête (import lancé avant son chargement). */
  private volatile String notice = "";

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
    else web.loadUrl("https://" + HOST + "/assets/www/index.html" + tabHash(getIntent()));
    if (state == null) receive(getIntent());
  }

  /** Fichier partagé vers l'appli, ou ouvert avec elle : dossier de candidature ou CV. */
  private void receive(Intent intent) {
    if (intent == null) return;
    Uri uri = null;
    if (Intent.ACTION_SEND.equals(intent.getAction())) uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
    else if (Intent.ACTION_VIEW.equals(intent.getAction())) uri = intent.getData();
    if (uri == null) return;
    intent.setAction(Intent.ACTION_MAIN);
    importFrom(uri);
  }

  private void importFrom(final Uri uri) {
    new Thread(() -> {
      boolean ok;
      String msg;
      try {
        byte[] data = Kit.readAll(getContentResolver().openInputStream(uri));
        msg = Kit.importBytes(getApplicationContext(), data, displayName(uri));
        ok = true;
      } catch (Exception e) {
        ok = false;
        msg = "Fichier non reconnu : choisissez le dossier envoyé par Claude, ou un CV en PDF";
      }
      notice = msg;
      final String js = "window.__kit&&(window.__kit(" + ok + "," + JSONObject.quote(msg) + "),true)";
      runOnUiThread(() -> web.evaluateJavascript(js, v -> { if ("true".equals(v)) notice = ""; }));
    }).start();
  }

  private String displayName(Uri uri) {
    try (Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
      if (c != null && c.moveToFirst()) {
        String n = c.getString(0);
        if (n != null) return n;
      }
    } catch (Exception e) {
      /* nom inconnu */
    }
    String last = uri.getLastPathSegment();
    return last == null ? "CV.pdf" : last;
  }

  @Override
  protected void onActivityResult(int requestCode, int resultCode, Intent data) {
    super.onActivityResult(requestCode, resultCode, data);
    if (requestCode == PICK && resultCode == RESULT_OK && data != null && data.getData() != null) importFrom(data.getData());
  }

  /** Envoie le CV (et éventuellement un message) vers une autre appli. */
  private void share(String to, String subject, String body, boolean emailOnly) {
    File cv = Kit.cv(getApplicationContext());
    Intent send = new Intent(Intent.ACTION_SEND);
    send.setType(cv != null ? "application/pdf" : "text/plain");
    if (to != null && !to.isEmpty()) send.putExtra(Intent.EXTRA_EMAIL, new String[]{to});
    if (subject != null && !subject.isEmpty()) send.putExtra(Intent.EXTRA_SUBJECT, subject);
    if (body != null && !body.isEmpty()) send.putExtra(Intent.EXTRA_TEXT, body);
    if (cv != null) {
      Uri u = FileProvider.getUriForFile(this, FILES, cv);
      send.putExtra(Intent.EXTRA_STREAM, u);
      send.setClipData(ClipData.newRawUri(cv.getName(), u));
      send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
    }
    if (emailOnly) {
      /* seules les applis d'e-mail sont proposées, avec la pièce jointe */
      Intent mail = new Intent(send);
      mail.setSelector(new Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:")));
      try {
        startActivity(mail);
        return;
      } catch (ActivityNotFoundException e) {
        /* aucune appli d'e-mail : choix libre */
      }
    }
    try {
      startActivity(Intent.createChooser(send, emailOnly ? "Envoyer la candidature" : "Partager le CV"));
    } catch (ActivityNotFoundException e) {
      /* aucune appli de partage */
    }
  }

  /** Onglet demandé par une notification ("#maroc"), ou rien. */
  private static String tabHash(Intent intent) {
    String tab = intent == null ? null : intent.getStringExtra("tab");
    return tab != null && tab.matches("[a-z]{1,12}") ? "#" + tab : "";
  }

  @Override
  protected void onNewIntent(Intent intent) {
    super.onNewIntent(intent);
    String hash = tabHash(intent);
    if (!hash.isEmpty()) web.evaluateJavascript("window.__tab&&window.__tab('" + hash.substring(1) + "')", null);
    receive(intent);
  }

  /** Vérifie la liste d'offres en arrière-plan et demande le droit d'afficher des notifications. */
  private void watchFeed() {
    Constraints net = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(FeedWorker.class, 1, TimeUnit.HOURS)
        .setConstraints(net)
        .build();
    WorkManager.getInstance(getApplicationContext())
        .enqueueUniquePeriodicWork("flux-offres", ExistingPeriodicWorkPolicy.UPDATE, req);
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
    /* la page ferme d'abord sa fiche ouverte, s'il y en a une */
    web.evaluateJavascript("(window.__back&&window.__back())?'1':'0'", v -> {
      if (v != null && v.contains("1")) return;
      if (web.canGoBack()) web.goBack();
      else finish();
    });
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

    /** Dossier de candidature importé (sans le CV), ou chaîne vide. */
    @JavascriptInterface
    public String kit() {
      return Kit.json(getApplicationContext());
    }

    @JavascriptInterface
    public String cvName() {
      File f = Kit.cv(getApplicationContext());
      return f == null ? "" : f.getName();
    }

    /** Choix du fichier à importer : dossier envoyé par Claude ou CV en PDF. */
    @JavascriptInterface
    public void pickKit() {
      runOnUiThread(() -> {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        try {
          startActivityForResult(i, PICK);
        } catch (ActivityNotFoundException e) {
          Intent g = new Intent(Intent.ACTION_GET_CONTENT);
          g.addCategory(Intent.CATEGORY_OPENABLE);
          g.setType("*/*");
          try { startActivityForResult(g, PICK); } catch (ActivityNotFoundException e2) { /* aucun sélecteur */ }
        }
      });
    }

    @JavascriptInterface
    public void copy(String text) {
      ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
      if (cm != null && text != null) cm.setPrimaryClip(ClipData.newPlainText("Candidature", text));
    }

    /** Ouvre une page (offre, formulaire) dans le navigateur. */
    @JavascriptInterface
    public void open(String url) {
      if (url == null || !url.startsWith("https://")) return;
      runOnUiThread(() -> {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (ActivityNotFoundException e) { /* aucun navigateur */ }
      });
    }

    /** E-mail de candidature : destinataire facultatif, objet, lettre, CV en pièce jointe. */
    @JavascriptInterface
    public void send(String json) {
      try {
        JSONObject o = new JSONObject(json == null ? "{}" : json);
        final String to = o.optString("to"), subject = o.optString("subject"), body = o.optString("body");
        runOnUiThread(() -> share(to, subject, body, true));
      } catch (Exception e) {
        /* message illisible */
      }
    }

    @JavascriptInterface
    public void shareCv() {
      runOnUiThread(() -> share(null, null, null, false));
    }

    @JavascriptInterface
    public boolean saveCv() {
      return Kit.saveToDownloads(getApplicationContext());
    }

    /** Candidatures envoyées, gardées pour le rappel de relance. */
    @JavascriptInterface
    public void saveApps(String json) {
      getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
          .putString("apps", json == null ? "" : json).apply();
    }

    /** Réglages des alertes : {"fortes":true,"autres":"discretes","relances":true}. */
    @JavascriptInterface
    public void setNotif(String json) {
      try {
        JSONObject o = new JSONObject(json == null ? "{}" : json);
        String autres = o.optString("autres", "discretes");
        if (!autres.equals("son") && !autres.equals("aucune")) autres = "discretes";
        getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putBoolean("notif_fortes", o.optBoolean("fortes", true))
            .putString("notif_autres", autres)
            .putBoolean("notif_relances", o.optBoolean("relances", true))
            .apply();
      } catch (Exception e) {
        /* réglage illisible : on garde l'ancien */
      }
    }

    @JavascriptInterface
    public String notifPrefs() {
      android.content.SharedPreferences p = getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
      try {
        return new JSONObject()
            .put("fortes", p.getBoolean("notif_fortes", true))
            .put("autres", p.getString("notif_autres", "discretes"))
            .put("relances", p.getBoolean("notif_relances", true))
            .toString();
      } catch (Exception e) {
        return "{}";
      }
    }

    /** Notification d'essai (et demande d'autorisation si besoin). */
    @JavascriptInterface
    public void testNotif() {
      runOnUiThread(() -> {
        if (Build.VERSION.SDK_INT >= 33
            && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
          requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 7);
        }
      });
      FeedWorker.test(getApplicationContext());
    }

    @JavascriptInterface
    public String notice() {
      String n = notice;
      notice = "";
      return n == null ? "" : n;
    }
  }
}
