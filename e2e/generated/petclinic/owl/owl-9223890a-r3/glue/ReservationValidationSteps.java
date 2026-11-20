package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import td.harness.Harness;

public class ReservationValidationSteps {
    private static final Set<String> NUMERIC = Set.of("nights", "animalCount", "roomNumber", "loyaltyPoints");

    private Map<String, Object> request;
    private Response response;
    private Integer existingId;

    private static Response post(Object body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    private Integer createValid() {
        request = ApiData.reservationBody();
        Response r = post(request);
        assertThat(r.statusCode()).as(r.asString()).isIn(200, 201);
        Integer id = ApiData.extractId(r);
        assertThat(id).isNotNull();
        return id;
    }

    @When("an empty reservation creation request is submitted")
    public void emptyRequest() {
        response = post("{}");
    }

    @Given("a valid reservation request for validation checks")
    public void validRequest() {
        request = ApiData.reservationBody();
    }

    @When("the reservation request field {string} is set to {string} and submitted")
    public void setField(String field, String value) {
        Object converted = NUMERIC.contains(field) ? (Object) Integer.valueOf(value) : value;
        request.put(field, converted);
        response = post(request);
    }

    @Given("a boarding reservation already exists for a room and check-in date")
    public void existingBooking() {
        existingId = createValid();
    }

    @When("another reservation is submitted for the same room and check-in date")
    public void anotherBooking() {
        Map<String, Object> other = ApiData.reservationBody();
        other.put("roomNumber", request.get("roomNumber"));
        other.put("checkInDate", request.get("checkInDate"));
        response = post(other);
    }

    @When("a reservation with id {int} is requested")
    public void getUnknown(int id) {
        response = Harness.authed().get("/api/reservations/" + id);
    }

    @When("the reservation with id {int} is updated with valid data")
    public void updateUnknown(int id) {
        response = Harness.authed().contentType("application/json").body(ApiData.reservationBody())
                .put("/api/reservations/" + id);
    }

    @When("the reservation with id {int} is deleted")
    public void deleteUnknown(int id) {
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @Given("an existing reservation for validation checks")
    public void existingReservation() {
        existingId = createValid();
    }

    @When("the existing reservation is updated with {int} nights")
    public void updateExisting(int nights) {
        Map<String, Object> body = new LinkedHashMap<>(request);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + existingId);
    }

    @Then("the reservation validation response status is {int}")
    public void status(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }
}
