package glue.support;

import io.restassured.response.Response;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiSupport {

    public static final String UNKNOWN_ID = "987654321";

    private ApiSupport() {
    }

    public static String letters(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append((char) ('a' + ThreadLocalRandom.current().nextInt(26)));
        }
        return sb.toString();
    }

    public static String digits(int length) {
        StringBuilder sb = new StringBuilder();
        sb.append((char) ('1' + ThreadLocalRandom.current().nextInt(9)));
        for (int i = 1; i < length; i++) {
            sb.append((char) ('0' + ThreadLocalRandom.current().nextInt(10)));
        }
        return sb.toString();
    }

    public static int randomInt(int min, int maxInclusive) {
        return ThreadLocalRandom.current().nextInt(min, maxInclusive + 1);
    }

    public static Map<String, Object> newReservationBody(int nights) {
        String suffix = letters(8);
        Map<String, Object> body = new HashMap<>();
        body.put("petName", "Pet" + suffix);
        body.put("ownerEmail", "e2e." + suffix + "@example.com");
        body.put("roomNumber", randomInt(1, 9));
        body.put("nights", nights);
        body.put("animalCount", 1);
        body.put("checkInDate", LocalDate.now().plusDays(randomInt(30, 330)).toString());
        return body;
    }

    public static Map<String, Object> newOwnerBody() {
        Map<String, Object> body = new HashMap<>();
        body.put("firstName", "Ann" + letters(6));
        body.put("lastName", "Tester" + letters(6));
        body.put("address", "1 Test Street " + letters(4));
        body.put("city", "Testville" + letters(4));
        body.put("telephone", digits(10));
        return body;
    }

    public static boolean isSuccess(int status) {
        return status >= 200 && status < 300;
    }

    public static String extractId(Response response) {
        try {
            Object id = response.jsonPath().get("id");
            if (id instanceof Number || id instanceof String) {
                return String.valueOf(id);
            }
        } catch (RuntimeException ignored) {
            // fall back to the Location header
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }

    public static Integer intField(Response response, String path) {
        Object value = response.jsonPath().get(path);
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        if (value instanceof String) {
            return Integer.valueOf((String) value);
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    public static List<Map<String, Object>> listItems(Response response) {
        List<Map<String, Object>> items = new ArrayList<>();
        Object root;
        try {
            root = response.jsonPath().get("$");
        } catch (RuntimeException e) {
            return items;
        }
        List<Object> candidates = null;
        if (root instanceof List) {
            candidates = (List<Object>) root;
        } else if (root instanceof Map) {
            for (Object value : ((Map<String, Object>) root).values()) {
                if (value instanceof List) {
                    candidates = (List<Object>) value;
                    break;
                }
            }
        }
        if (candidates != null) {
            for (Object candidate : candidates) {
                if (candidate instanceof Map) {
                    items.add((Map<String, Object>) candidate);
                }
            }
        }
        return items;
    }

    public static boolean looksLikeJson(String body) {
        if (body == null) {
            return false;
        }
        String trimmed = body.trim();
        return trimmed.startsWith("[") || trimmed.startsWith("{");
    }
}
