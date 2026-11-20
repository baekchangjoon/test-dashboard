package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import td.harness.Harness;

public final class ApiSupport {

    private static final String LETTERS = "abcdefghijklmnopqrstuvwxyz";

    private ApiSupport() {
    }

    public static String randomLetters(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append(LETTERS.charAt(ThreadLocalRandom.current().nextInt(LETTERS.length())));
        }
        return sb.toString();
    }

    public static String randomDigits(int length) {
        StringBuilder sb = new StringBuilder();
        sb.append(1 + ThreadLocalRandom.current().nextInt(9));
        for (int i = 1; i < length; i++) {
            sb.append(ThreadLocalRandom.current().nextInt(10));
        }
        return sb.toString();
    }

    public static String extractId(Response response) {
        String id = null;
        try {
            Object value = response.jsonPath().get("id");
            if (value != null) {
                id = String.valueOf(value);
            }
        } catch (RuntimeException e) {
            id = null;
        }
        if (id == null || id.isBlank()) {
            String location = response.header("Location");
            if (location != null && !location.isBlank()) {
                String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
                id = trimmed.substring(trimmed.lastIndexOf('/') + 1);
            }
        }
        return id;
    }

    public static Map<String, Object> reservationBody(int nights) {
        Map<String, Object> body = new HashMap<>();
        body.put("petName", "Pet" + randomLetters(8));
        body.put("ownerEmail", "owner." + randomLetters(10) + "@example.com");
        body.put("roomNumber", 1 + ThreadLocalRandom.current().nextInt(20));
        body.put("nights", nights);
        body.put("animalCount", 1);
        body.put("checkInDate", LocalDate.now().plusDays(14 + ThreadLocalRandom.current().nextInt(280)).toString());
        return body;
    }

    public static Map<String, Object> ownerBody() {
        Map<String, Object> body = new HashMap<>();
        body.put("firstName", "Ann" + randomLetters(6));
        body.put("lastName", "Tester" + randomLetters(6));
        body.put("address", "12 Test Street");
        body.put("city", "Testville" + randomLetters(5));
        body.put("telephone", randomDigits(10));
        return body;
    }

    public static Response postJson(String path, Object body) {
        return Harness.authed().contentType("application/json").body(body).post(path);
    }

    public static Response putJson(String path, Object body) {
        return Harness.authed().contentType("application/json").body(body).put(path);
    }
}
