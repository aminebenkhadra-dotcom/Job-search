package com.radaremploi.app;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Lit la liste d'offres évaluées et prévient quand de nouvelles offres y apparaissent. */
public class FeedWorker extends Worker {
  static final String FEED = "https://raw.githubusercontent.com/aminebenkhadra-dotcom/Job-search/main/data/offres.json";

  public FeedWorker(Context context, WorkerParameters params) {
    super(context, params);
  }

  @Override
  public Result doWork() {
    Context ctx = getApplicationContext();
    try {
      Net.Reply r = Net.call("GET", FEED, null, null);
      if (r.status != 200) return Result.success();
      JSONArray offers = new JSONObject(r.body).optJSONArray("offers");
      if (offers == null) return Result.success();

      SharedPreferences prefs = ctx.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
      Set<String> stored = prefs.getStringSet("feed_seen", null);
      boolean first = stored == null;
      Set<String> seen = first ? new HashSet<String>() : new HashSet<>(stored);
      List<String> fresh = new ArrayList<>();
      for (int i = 0; i < offers.length(); i++) {
        JSONObject o = offers.optJSONObject(i);
        if (o == null) continue;
        String id = o.optString("id");
        String title = o.optString("title");
        if (id.isEmpty() || title.isEmpty() || seen.contains(id)) continue;
        seen.add(id);
        if (!first) fresh.add(o.optInt("chances") + " % · " + title + " · " + o.optString("place"));
      }
      if (seen.size() > 2000) seen = new HashSet<>(new ArrayList<>(seen).subList(0, 1000));
      prefs.edit().putStringSet("feed_seen", seen).apply();
      if (!fresh.isEmpty()) AlertWorker.announce(ctx, fresh, 2);
    } catch (Exception e) {
      /* prochain passage */
    }
    return Result.success();
  }
}
