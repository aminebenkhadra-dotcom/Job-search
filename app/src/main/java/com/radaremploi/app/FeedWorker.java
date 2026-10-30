package com.radaremploi.app;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Lit les listes d'offres évaluées (sélection tous pays, marché marocain) et prévient des nouvelles. */
public class FeedWorker extends Worker {
  static final String BASE = "https://raw.githubusercontent.com/aminebenkhadra-dotcom/Job-search/main/data/";
  /** Au Maroc, on ne notifie que les offres où les chances atteignent ce seuil. */
  private static final int MAROC_MIN = 40;
  /** À partir de ce niveau, l'offre a sa propre alerte, immédiate et sonore. */
  static final int STRONG = 75;

  public FeedWorker(Context context, WorkerParameters params) {
    super(context, params);
  }

  @Override
  public Result doWork() {
    Context ctx = getApplicationContext();
    SharedPreferences prefs = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
    boolean strongOn = prefs.getBoolean("notif_fortes", true);
    String others = prefs.getString("notif_autres", "discretes");  // son | discretes | aucune
    Set<String> announced = new HashSet<>();
    List<String> strong = new ArrayList<>();
    List<String> feed = new ArrayList<>();
    List<String> maroc = new ArrayList<>();
    check(ctx, "offres.json", "feed_seen", 0, announced, strong, feed);
    check(ctx, "maroc.json", "maroc_seen", MAROC_MIN, announced, strong, maroc);
    if (strongOn && !strong.isEmpty()) {
      String first = strong.get(0);
      String title = strong.size() == 1
          ? "Offre à " + first.substring(0, first.indexOf(" %")) + " % : " + first.split(" · ")[1]
          : strong.size() + " offres à 75 % et plus";
      AlertWorker.notify(ctx, strong, 5, "feed", title, AlertWorker.CH_STRONG);
    }
    if (!"aucune".equals(others)) {
      String channel = "son".equals(others) ? AlertWorker.CHANNEL : AlertWorker.CH_QUIET;
      int n = feed.size();
      if (n > 0) AlertWorker.notify(ctx, feed, 2, "feed", n == 1 ? "1 nouvelle offre pour vous" : n + " nouvelles offres pour vous", channel);
      n = maroc.size();
      if (n > 0) AlertWorker.notify(ctx, maroc, 3, "maroc", n == 1 ? "1 nouvelle offre au Maroc" : n + " nouvelles offres au Maroc", channel);
    }
    if (prefs.getBoolean("notif_relances", true)) remind(ctx);
    return Result.success();
  }

  /** Notification d'essai, depuis les réglages. */
  static void test(Context ctx) {
    List<String> l = new ArrayList<>();
    l.add("80 % · Trade Marketing Manager · Casablanca");
    l.add("Exemple : voici à quoi ressemble une alerte « fortes chances ».");
    AlertWorker.notify(ctx, l, 9, "feed", "Test : offre à 80 %", AlertWorker.CH_STRONG);
  }

  /** Candidatures sans réponse : rappel 7 jours après l'envoi, puis 10 jours après une relance. Une seule fois chacune. */
  static void remind(Context ctx) {
    SharedPreferences prefs = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
    String raw = prefs.getString("apps", "");
    if (raw == null || raw.isEmpty()) return;
    try {
      JSONArray apps = new JSONArray(raw);
      Set<String> done = new HashSet<>(prefs.getStringSet("apps_reminded", new HashSet<String>()));
      SimpleDateFormat day = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
      long now = System.currentTimeMillis();
      List<String> lines = new ArrayList<>();
      for (int i = 0; i < apps.length(); i++) {
        JSONObject a = apps.optJSONObject(i);
        if (a == null) continue;
        String status = a.optString("status");
        String since;
        int wait;
        if ("envoyee".equals(status)) { since = a.optString("sent"); wait = 7; }
        else if ("relancee".equals(status)) { since = a.optString("relance", a.optString("sent")); wait = 10; }
        else continue;
        Date d;
        try { d = day.parse(since); } catch (Exception e) { continue; }
        if (d == null || now - d.getTime() < wait * 86400000L) continue;
        String key = a.optString("id") + "|" + status + "|" + since;
        if (done.contains(key)) continue;
        done.add(key);
        String company = a.optString("company").split(" · ")[0];
        lines.add(a.optString("title") + (company.isEmpty() ? "" : " · " + company));
      }
      if (done.size() > 500) done = new HashSet<>(new ArrayList<>(done).subList(0, 250));
      prefs.edit().putStringSet("apps_reminded", done).apply();
      int n = lines.size();
      if (n > 0) AlertWorker.notify(ctx, lines, 4, "suivi", n == 1 ? "1 candidature à relancer" : n + " candidatures à relancer");
    } catch (Exception e) {
      /* prochain passage */
    }
  }

  /**
   * Compare une liste aux offres déjà vues. Le premier passage sert de point de départ et ne notifie rien.
   * Une offre déjà annoncée par une autre liste pendant ce passage n'est pas annoncée deux fois.
   * Les offres à 75 % et plus vont dans « strong », les autres (à partir de minChances) dans « others ».
   */
  private void check(Context ctx, String file, String key, int minChances, Set<String> announced,
      List<String> strong, List<String> others) {
    try {
      Net.Reply r = Net.call("GET", BASE + file, null, null);
      if (r.status != 200) return;
      JSONArray offers = new JSONObject(r.body).optJSONArray("offers");
      if (offers == null) return;

      SharedPreferences prefs = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
      Set<String> stored = prefs.getStringSet(key, null);
      boolean first = stored == null;
      Set<String> seen = first ? new HashSet<String>() : new HashSet<>(stored);
      for (int i = 0; i < offers.length(); i++) {
        JSONObject o = offers.optJSONObject(i);
        if (o == null) continue;
        String id = o.optString("id");
        String title = o.optString("title");
        if (id.isEmpty() || title.isEmpty() || seen.contains(id)) continue;
        seen.add(id);
        int chances = o.optInt("chances");
        if (first || announced.contains(id) || chances < minChances) continue;
        announced.add(id);
        String line = chances + " % · " + title + " · " + o.optString("place");
        if (chances >= STRONG) strong.add(line);
        else others.add(line);
      }
      if (seen.size() > 3000) seen = new HashSet<>(new ArrayList<>(seen).subList(0, 1500));
      prefs.edit().putStringSet(key, seen).apply();
    } catch (Exception e) {
      /* prochain passage */
    }
  }
}
