package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiData {
    private static final String ALPHA = "abcdefghijklmnopqrstuvwxyz";

    private ApiData() {
    }

    public static String letters(int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(ALPHA.charAt(ThreadLocalRandom.current().nextInt(ALPHA.length())));
        }
        return sb.toString();
    }

    public static String digits(int n) {
        StringBuilder sb = new StringBuilder();
        sb.append(ThreadLocalRandom.current().nextInt(1, 10));
        for (int i = 1; i < n; i++) {
            sb.append(ThreadLocalRandom.current().nextInt(10));
        }
        return sb.toString();
    }

    public static Map<String, Object> ownerBody() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("firstName", "Ann" + letters(8));
        m.put("lastName", "Tester" + letters(8));
        m.put("address", digits(3) + " Main Street");
        m.put("city", "Springfield");
        m.put("telephone", digits(10));
        return m;
    }

    public static Map<String, Object> reservationBody() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("petName", "Pet" + letters(8));
        m.put("ownerEmail", "owner." + letters(10) + "@example.com");
        m.put("roomNumber", ThreadLocalRandom.current().nextInt(1, 11));
        m.put("nights", 2);
        m.put("animalCount", 1);
        m.put("loyaltyPoints", 0);
        m.put("checkInDate", LocalDate.now().plusDays(ThreadLocalRandom.current().nextLong(30, 330)).toString());
        return m;
    }

    public static Integer extractId(Response r) {
        Object id;
        try {
            id = r.jsonPath().get("id");
        } catch (Exception e) {
            id = null;
        }
        if (id instanceof Number) {
            return ((Number) id).intValue();
        }
        if (id != null) {
            try {
                return Integer.valueOf(id.toString().trim());
            } catch (NumberFormatException e) {
                // fall through to Location header
            }
        }
        String loc = r.header("Location");
        if (loc != null && !loc.isBlank()) {
            String s = loc.endsWith("/") ? loc.substring(0, loc.length() - 1) : loc;
            String last = s.substring(s.lastIndexOf('/') + 1);
            try {
                return Integer.valueOf(last);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    public static List<Object> fieldValues(Response r, String field) {
        List<Object> out = new ArrayList<>();
        try {
            List<Object> l = r.jsonPath().getList(field);
            if (l != null) {
                out.addAll(l);
                return out;
            }
        } catch (Exception e) {
            // try paged shape below
        }
        try {
            List<Object> l = r.jsonPath().getList("content." + field);
            if (l != null) {
                out.addAll(l);
            }
        } catch (Exception e) {
            // unknown shape
        }
        return out;
    }

    public static List<Integer> ids(Response r) {
        List<Integer> out = new ArrayList<>();
        for (Object o : fieldValues(r, "id")) {
            if (o instanceof Number) {
                out.add(((Number) o).intValue());
            } else if (o != null) {
                try {
                    out.add(Integer.valueOf(o.toString().trim()));
                } catch (NumberFormatException e) {
                    // ignore non numeric id
                }
            }
        }
        return out;
    }

    public static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
