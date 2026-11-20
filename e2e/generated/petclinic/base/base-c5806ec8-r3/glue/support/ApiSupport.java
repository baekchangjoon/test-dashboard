package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import td.harness.Harness;

public final class ApiSupport {

    public static final String UNKNOWN_ID = "987654321";

    private ApiSupport() {
    }

    public static String suffix() {
        return Long.toString(System.nanoTime(), 36) + ThreadLocalRandom.current().nextInt(1000, 10000);
    }

    public static String toJson(Map<String, Object> map) {
        StringBuilder sb = new StringBuilder();
        sb.append('{');
        boolean first = true;
        for (Map.Entry<String, Object> e : map.entrySet()) {
            if (!first) {
                sb.append(',');
            }
            first = false;
            appendString(sb, e.getKey());
            sb.append(':');
            Object v = e.getValue();
            if (v == null) {
                sb.append("null");
            } else if (v instanceof Number || v instanceof Boolean) {
                sb.append(v);
            } else {
                appendString(sb, String.valueOf(v));
            }
        }
        sb.append('}');
        return sb.toString();
    }

    private static void appendString(StringBuilder sb, String s) {
        sb.append((char) 34);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == 34 || c == 92) {
                sb.append((char) 92);
            }
            sb.append(c);
        }
        sb.append((char) 34);
    }

    public static String extractId(Response response) {
        try {
            Object id = response.jsonPath().get("id");
            if (id != null) {
                return String.valueOf(id);
            }
        } catch (Exception ignored) {
            // fall back to the Location header
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }

    public static int randomRoom() {
        return ThreadLocalRandom.current().nextInt(1, 10);
    }

    public static String randomCheckInDate() {
        return LocalDate.now().plusDays(ThreadLocalRandom.current().nextInt(30, 700)).toString();
    }

    public static Map<String, Object> newReservationBody() {
        String s = suffix();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("petName", "Pet" + s);
        body.put("ownerEmail", "owner" + s + "@example.com");
        body.put("roomNumber", randomRoom());
        body.put("nights", 2);
        body.put("animalCount", 1);
        body.put("checkInDate", randomCheckInDate());
        return body;
    }

    public static Response postReservation(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(toJson(body)).post("/api/reservations");
    }

    public static Response createReservation(Map<String, Object> body) {
        Response r = postReservation(body);
        int attempts = 1;
        while (r.statusCode() == 409 && attempts < 6) {
            body.put("roomNumber", randomRoom());
            body.put("checkInDate", randomCheckInDate());
            r = postReservation(body);
            attempts++;
        }
        return r;
    }

    public static Map<String, Object> newOwnerBody() {
        String s = suffix();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("address", "Street " + s);
        body.put("city", "City" + s);
        body.put("telephone", "5" + ThreadLocalRandom.current().nextInt(100000000, 1000000000));
        return body;
    }
}
