package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiData {

    private ApiData() {
    }

    public static String suffix() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 10);
    }

    public static String letters() {
        String s = suffix();
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            if (Character.isDigit(c)) {
                b.append((char) ('a' + (c - '0')));
            } else {
                b.append(c);
            }
        }
        return b.toString();
    }

    public static int randomInt(int minInclusive, int maxInclusive) {
        return ThreadLocalRandom.current().nextInt(minInclusive, maxInclusive + 1);
    }

    public static int unknownId() {
        return 900000000 + randomInt(0, 99999999);
    }

    public static String telephone() {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < 10; i++) {
            b.append(randomInt(0, 9));
        }
        return b.toString();
    }

    public static String futureDate() {
        return LocalDate.now().plusDays(randomInt(30, 330)).toString();
    }

    public static Map<String, Object> ownerBody() {
        String s = letters();
        Map<String, Object> m = new HashMap<>();
        m.put("firstName", "Ann" + s);
        m.put("lastName", "Lee" + s);
        m.put("address", "1 Test Street " + s);
        m.put("city", "Town" + s);
        m.put("telephone", telephone());
        return m;
    }

    public static Map<String, Object> reservationBody() {
        String s = suffix();
        Map<String, Object> m = new HashMap<>();
        m.put("petName", "Pet" + s);
        m.put("ownerEmail", "owner" + s + "@example.com");
        m.put("roomNumber", randomInt(1, 10));
        m.put("nights", 2);
        m.put("animalCount", 1);
        m.put("checkInDate", futureDate());
        return m;
    }

    public static String extractId(Response r) {
        Object id = null;
        try {
            id = r.jsonPath().get("id");
        } catch (RuntimeException e) {
            id = null;
        }
        if (id != null) {
            return String.valueOf(id);
        }
        String loc = r.header("Location");
        if (loc != null && !loc.isEmpty()) {
            String t = loc.endsWith("/") ? loc.substring(0, loc.length() - 1) : loc;
            return t.substring(t.lastIndexOf('/') + 1);
        }
        return null;
    }
}
