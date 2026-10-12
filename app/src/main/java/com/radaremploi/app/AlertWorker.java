package com.radaremploi.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Une fois par jour : cherche les offres publiées aujourd'hui et prévient s'il y en a de nouvelles. */
public class AlertWorker extends Worker {
  private static final String CHANNEL = "offres";
  private static final int MAX_COUNTRIES = 3;

  public AlertWorker(Context context, WorkerParameters params) {
    super(context, params);
  }

  @Override
  public Result doWork() {
    Context ctx = getApplicationContext();
    SharedPreferences prefs = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
    String cfg = prefs.getString("config", "");
    if (cfg == null || cfg.isEmpty()) return Result.success();
    try {
      JSONObject c = new JSONObject(cfg);
      String key = c.optString("key");
      boolean own = "own".equals(c.optString("prov"));
      JSONArray queries = c.optJSONArray("queries");
      JSONArray countries = c.optJSONArray("countries");
      if (key.isEmpty() || queries == null || queries.length() == 0 || countries == null) return Result.success();

      Set<String> seen = new HashSet<>(prefs.getStringSet("seen", new HashSet<String>()));
      List<String> fresh = new ArrayList<>();
      Map<String, String> headers = new HashMap<>();
      if (own) {
        headers.put("x-api-key", key);
      } else {
        headers.put("X-RapidAPI-Key", key);
        headers.put("X-RapidAPI-Host", "jsearch.p.rapidapi.com");
      }
      String base = own ? "https://api.openwebninja.com/jsearch/search" : "https://jsearch.p.rapidapi.com/search";

      for (int i = 0; i < countries.length() && i < MAX_COUNTRIES; i++) {
        JSONObject co = countries.getJSONObject(i);
        String q = queries.getString(0) + " in " + co.optString("loc");
        String url = base + "?query=" + URLEncoder.encode(q, "UTF-8") + "&page=1&num_pages=1&date_posted=today&country="
            + co.optString("code").toLowerCase(Locale.ROOT);
        Net.Reply r = Net.call("GET", url, headers, null);
        if (r.status != 200) continue;
        JSONArray data = new JSONObject(r.body).optJSONArray("data");
        if (data == null) continue;
        for (int j = 0; j < data.length(); j++) {
          JSONObject job = data.optJSONObject(j);
          if (job == null) continue;
          String id = job.optString("job_id");
          String title = job.optString("job_title");
          if (id.isEmpty() || title.isEmpty() || seen.contains(id)) continue;
          seen.add(id);
          String employer = job.optString("employer_name");
          fresh.add(title + (employer.isEmpty() ? "" : " · " + employer) + " · " + co.optString("name"));
        }
      }

      if (seen.size() > 3000) seen = new HashSet<>(new ArrayList<>(seen).subList(0, 1500));
      prefs.edit().putStringSet("seen", seen).apply();
      if (!fresh.isEmpty()) announce(ctx, fresh, 1, "search", "aujourd'hui");
    } catch (Exception e) {
      /* on réessaiera au prochain passage, sans consommer davantage de requêtes */
    }
    return Result.success();
  }

  /** Affiche une notification ; la toucher ouvre l'appli sur l'onglet indiqué. */
  static void announce(Context ctx, List<String> fresh, int notifId, String tab, String label) {
    NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
    if (nm == null) return;
    if (Build.VERSION.SDK_INT >= 26) {
      nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Nouvelles offres", NotificationManager.IMPORTANCE_DEFAULT));
    }
    Intent open = new Intent(ctx, MainActivity.class);
    open.putExtra("tab", tab);
    open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
    PendingIntent pi = PendingIntent.getActivity(ctx, notifId, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

    StringBuilder lines = new StringBuilder();
    for (int i = 0; i < fresh.size() && i < 5; i++) {
      if (i > 0) lines.append('\n');
      lines.append(fresh.get(i));
    }
    int n = fresh.size();
    String title = n == 1 ? "1 nouvelle offre " + label : n + " nouvelles offres " + label;

    Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
    b.setSmallIcon(android.R.drawable.ic_menu_search)
        .setContentTitle(title)
        .setContentText(fresh.get(0))
        .setStyle(new Notification.BigTextStyle().bigText(lines.toString()))
        .setContentIntent(pi)
        .setAutoCancel(true);
    try {
      nm.notify(notifId, b.build());
    } catch (SecurityException e) {
      /* notifications refusées par l'utilisateur */
    }
  }
}
