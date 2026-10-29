package com.radaremploi.app;

import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Dossier de candidature privé : CV en PDF et lettres, importés depuis un fichier sur le téléphone.
 * Rien de personnel n'est livré avec l'appli ; tout reste dans son espace privé.
 */
final class Kit {
  static final int MAX_BYTES = 20 * 1024 * 1024;

  private Kit() {}

  private static File cvDir(Context c) {
    File d = new File(c.getFilesDir(), "cv");
    if (!d.isDirectory()) d.mkdirs();
    return d;
  }

  private static File kitFile(Context c) {
    return new File(c.getFilesDir(), "kit.json");
  }

  /** Le CV enregistré, ou null. */
  static File cv(Context c) {
    File[] f = cvDir(c).listFiles();
    return f != null && f.length > 0 ? f[0] : null;
  }

  /** Le dossier sans le CV (JSON), ou une chaîne vide. */
  static String json(Context c) {
    File f = kitFile(c);
    if (!f.isFile()) return "";
    try {
      return new String(readAll(new FileInputStream(f)), StandardCharsets.UTF_8);
    } catch (IOException e) {
      return "";
    }
  }

  /** Importe un PDF (le CV seul) ou un dossier JSON ; renvoie le message à afficher. */
  static String importBytes(Context c, byte[] data, String name) throws Exception {
    if (isPdf(data)) {
      saveCv(c, data, name);
      return "CV enregistré";
    }
    String s = new String(data, StandardCharsets.UTF_8).trim();
    if (s.startsWith("﻿")) s = s.substring(1);
    JSONObject k = new JSONObject(s);
    if (k.optInt("radar_kit", 0) < 1) throw new IllegalArgumentException("pas un dossier");
    JSONObject cv = k.optJSONObject("cv");
    boolean withCv = false;
    if (cv != null) {
      byte[] pdf = Base64.decode(cv.optString("data", ""), Base64.DEFAULT);
      if (isPdf(pdf)) {
        saveCv(c, pdf, cv.optString("name", "CV.pdf"));
        withCv = true;
      }
      k.remove("cv");
    }
    write(kitFile(c), k.toString().getBytes(StandardCharsets.UTF_8));
    return withCv ? "Dossier importé : lettres et CV prêts" : "Dossier importé";
  }

  private static boolean isPdf(byte[] b) {
    return b != null && b.length > 4 && b[0] == '%' && b[1] == 'P' && b[2] == 'D' && b[3] == 'F';
  }

  private static void saveCv(Context c, byte[] pdf, String name) throws IOException {
    File[] old = cvDir(c).listFiles();
    if (old != null) for (File f : old) f.delete();
    write(new File(cvDir(c), safeName(name)), pdf);
  }

  private static String safeName(String n) {
    n = n == null ? "" : n.replaceAll("[^A-Za-z0-9._-]+", "_");
    if (n.isEmpty() || n.startsWith(".")) n = "CV" + n;
    if (!n.toLowerCase().endsWith(".pdf")) n = n + ".pdf";
    return n.length() > 80 ? n.substring(n.length() - 80) : n;
  }

  /** Copie le CV dans le dossier Téléchargements (Android 10 et plus). */
  static boolean saveToDownloads(Context c) {
    File cv = cv(c);
    if (cv == null || Build.VERSION.SDK_INT < 29) return false;
    try {
      ContentValues v = new ContentValues();
      v.put(MediaStore.MediaColumns.DISPLAY_NAME, cv.getName());
      v.put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf");
      Uri u = c.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
      if (u == null) return false;
      try (OutputStream out = c.getContentResolver().openOutputStream(u)) {
        if (out == null) return false;
        out.write(readAll(new FileInputStream(cv)));
      }
      return true;
    } catch (Exception e) {
      return false;
    }
  }

  static byte[] readAll(InputStream in) throws IOException {
    if (in == null) throw new IOException("flux vide");
    try (InputStream s = in) {
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      byte[] buf = new byte[16384];
      int n;
      while ((n = s.read(buf)) > 0) {
        out.write(buf, 0, n);
        if (out.size() > MAX_BYTES) throw new IOException("fichier trop gros");
      }
      return out.toByteArray();
    }
  }

  private static void write(File f, byte[] data) throws IOException {
    File tmp = new File(f.getPath() + ".tmp");
    try (FileOutputStream out = new FileOutputStream(tmp)) {
      out.write(data);
    }
    if (!tmp.renameTo(f)) {
      f.delete();
      if (!tmp.renameTo(f)) throw new IOException("écriture impossible");
    }
  }
}
