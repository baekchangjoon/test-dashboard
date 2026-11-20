package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import td.harness.Harness;

public final class ApiData {

    private ApiData() {
    }

    public static int between(int min, int max) {
        return ThreadLocalRandom.current().nextInt(min, max + 1);
    }

    public static String letters(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append((char) ('a' + ThreadLocalRandom.current().nextInt(26)));
        }
        return sb.toString();
    }

    public static String uniqueName(String prefix) {
        return prefix + letters(10);
    }

    public static String phoneDigits() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 10; i++) {
            sb.append(ThreadLocalRandom.current().nextInt(10));
        }
        return sb.toString();
    }

    public static String futureDate() {
        return LocalDate.now().plusDays(between(7, 365)).toString();
    }

    public static boolean isSuccess(int statusCode) {
        return statusCode >= 200 && statusCode <= 299;
    }

    public static Map<String, Object> reservationBody(String petName, int nights) {
        Map<String, Object> body = new HashMap<>();
        body.put("petName", petName);
        body.put("ownerEmail", petName.toLowerCase() + "@example.com");
        body.put("roomNumber", between(1, 10));
        body.put("nights", nights);
        body.put("animalCount", 1);
        body.put("checkInDate", futureDate());
        return body;
    }

    public static Response postReservation(Object body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    public static Response createReservation(Map<String, Object> body) {
        Response response = postReservation(body);
        int attempts = 0;
        while (response.statusCode() == 409 && attempts < 6) {
            body.put("roomNumber", between(1, 10));
            body.put("checkInDate", futureDate());
            response = postReservation(body);
            attempts++;
        }
        return response;
    }

    public static Map<String, Object> ownerBody(String firstName, String lastName, String city, String telephone) {
        Map<String, Object> body = new HashMap<>();
        body.put("firstName", firstName);
        body.put("lastName", lastName);
        body.put("address", "12 Test Street");
        body.put("city", city);
        body.put("telephone", telephone);
        return body;
    }

    public static Response postOwner(Object body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }

    public static Integer extractId(Response response) {
        Object value = null;
        try {
            value = response.jsonPath().get("id");
        } catch (RuntimeException e) {
            value = null;
        }
        if (value != null) {
            try {
                return Integer.valueOf(value.toString());
            } catch (NumberFormatException e) {
                value = null;
            }
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String last = location.substring(location.lastIndexOf('/') + 1).trim();
            try {
                return Integer.valueOf(last);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    public static List<String> idsInList(Response response) {
        List<String> ids = new ArrayList<>();
        String text = response.asString() == null ? "" : response.asString().trim();
        List<Object> raw = null;
        try {
            if (text.startsWith("[")) {
                raw = response.jsonPath().getList("id");
            } else if (text.startsWith("{")) {
                raw = response.jsonPath().getList("content.id");
            }
        } catch (RuntimeException e) {
            raw = null;
        }
        if (raw != null) {
            for (Object o : raw) {
                if (o != null) {
                    ids.add(o.toString());
                }
            }
        }
        return ids;
    }
}
