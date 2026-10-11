package com.radaremploi.app;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Appels HTTPS vers les seuls services utilisés par l'appli. */
final class Net {
  static final Set<String> HOSTS = new HashSet<>(Arrays.asList(
      "jsearch.p.rapidapi.com", "api.openwebninja.com", "api.anthropic.com", "raw.githubusercontent.com"));

  static final class Reply {
    final int status;
    final String body;
    Reply(int status, String body) { this.status = status; this.body = body; }
  }

  private Net() {}

  static Reply call(String method, String url, Map<String, String> headers, String body) {
    HttpURLConnection c = null;
    try {
      URL u = new URL(url);
      if (!"https".equals(u.getProtocol()) || !HOSTS.contains(u.getHost())) return new Reply(0, "host");
      c = (HttpURLConnection) u.openConnection();
      c.setRequestMethod(method);
      c.setConnectTimeout(20000);
      c.setReadTimeout(120000);
      if (headers != null) for (Map.Entry<String, String> e : headers.entrySet()) c.setRequestProperty(e.getKey(), e.getValue());
      if (body != null && body.length() > 0 && !"GET".equals(method)) {
        c.setDoOutput(true);
        try (OutputStream o = c.getOutputStream()) { o.write(body.getBytes(StandardCharsets.UTF_8)); }
      }
      int status = c.getResponseCode();
      InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
      return new Reply(status, read(in));
    } catch (Exception e) {
      return new Reply(0, String.valueOf(e.getMessage()));
    } finally {
      if (c != null) c.disconnect();
    }
  }

  private static String read(InputStream in) throws Exception {
    if (in == null) return "";
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    byte[] buf = new byte[8192];
    int n;
    try {
      while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    } finally {
      in.close();
    }
    return new String(out.toByteArray(), StandardCharsets.UTF_8);
  }
}
