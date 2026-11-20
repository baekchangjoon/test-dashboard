package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import td.harness.Harness;

public final class ApiData {

    private ApiData() {
    }

    public static String suffix() {
        String letters = "abcdefghijklmnopqrstuvwxyz";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 10; i++) {
            sb.append(letters.charAt(ThreadLocalRandom.current().nextInt(letters.length())));
        }
        return sb.toString();
    }

    public static String digits(int count) {
        StringBuilder sb = new StringBuilder();
        sb.append(1 + ThreadLocalRandom.current().nextInt(9));
        for (int i = 1; i < count; i++) {
            sb.append(ThreadLocalRandom.current().nextInt(10));
        }
        return sb.toString();
    }

    public static int unknownId() {
        return 900000000 + ThreadLocalRandom.current().nextInt(90000000);
    }

    public static Map<String, Object> reservationPayload() {
        String s = suffix();
        Map<String, Object> m = new HashMap<>();
        m.put("petName", "Pet" + s);
        m.put("ownerEmail", "owner." + s + "@example.com");
        m.put("nights", 3);
        m.put("animalCount", 1);
        reshuffleReservationSlot(m);
        return m;
    }

    public static void reshuffleReservationSlot(Map<String, Object> payload) {
        payload.put("roomNumber", 1 + ThreadLocalRandom.current().nextInt(10));
        payload.put("checkInDate", LocalDate.now().plusDays(7 + ThreadLocalRandom.current().nextInt(300)).toString());
    }

    public static Response postReservation(Map<String, Object> payload) {
        Response response = null;
        for (int attempt = 0; attempt < 6; attempt++) {
            response = Harness.authed().contentType("application/json").body(payload).post("/api/reservations");
            if (response.statusCode() != 409) {
                return response;
            }
            reshuffleReservationSlot(payload);
        }
        return response;
    }

    public static Map<String, Object> ownerPayload() {
        String s = suffix();
        Map<String, Object> m = new HashMap<>();
        m.put("firstName", "Ann" + s);
        m.put("lastName", "Tester" + s);
        m.put("address", s + " Street 1");
        m.put("city", "City" + s);
        m.put("telephone", digits(10));
        return m;
    }

    public static Integer extractId(Response response) {
        if (response == null) {
            return null;
        }
        try {
            Object value = response.jsonPath().get("id");
            if (value instanceof Number) {
                return ((Number) value).intValue();
            }
            if (value != null) {
                return Integer.valueOf(value.toString());
            }
        } catch (RuntimeException ignored) {
            // fall back to Location header
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.replaceAll("/+$", "");
            try {
                return Integer.valueOf(trimmed.substring(trimmed.lastIndexOf('/') + 1));
            } catch (RuntimeException ignored) {
                return null;
            }
        }
        return null;
    }

    public static boolean listContainsId(List<Object> ids, Object id) {
        if (ids == null || id == null) {
            return false;
        }
        String wanted = String.valueOf(id);
        for (Object o : ids) {
            if (o != null && wanted.equals(String.valueOf(o))) {
                return true;
            }
        }
        return false;
    }

    public static String describe(Response response) {
        return "HTTP " + response.statusCode() + ": " + response.asString();
    }
}
