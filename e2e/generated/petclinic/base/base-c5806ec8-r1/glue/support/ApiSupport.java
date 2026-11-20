package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiSupport {

    public static final String UNKNOWN_ID = "987654321";

    private ApiSupport() {
    }

    public static String suffix() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 10);
    }

    public static int randomRoom() {
        return ThreadLocalRandom.current().nextInt(1, 10);
    }

    public static String randomFutureDate() {
        return LocalDate.now().plusDays(ThreadLocalRandom.current().nextInt(14, 365)).toString();
    }

    public static String randomDigits(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append(ThreadLocalRandom.current().nextInt(0, 10));
        }
        return sb.toString();
    }

    public static Map<String, Object> reservationBody(String petName, String ownerEmail, int roomNumber, int nights, String checkInDate) {
        Map<String, Object> body = new HashMap<>();
        body.put("petName", petName);
        body.put("ownerEmail", ownerEmail);
        body.put("roomNumber", roomNumber);
        body.put("nights", nights);
        body.put("animalCount", 1);
        body.put("checkInDate", checkInDate);
        return body;
    }

    public static Map<String, Object> randomReservationBody(int nights) {
        String s = suffix();
        return reservationBody("Pet" + s, "owner" + s + "@example.com", randomRoom(), nights, randomFutureDate());
    }

    public static String extractId(Response response) {
        try {
            Object id = response.jsonPath().get("id");
            if (id != null) {
                return String.valueOf(id);
            }
        } catch (Exception ignored) {
            // body is not JSON or has no id field; fall back to Location header
        }
        String location = response.header("Location");
        if (location != null && !location.isEmpty()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }
}
