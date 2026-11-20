package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationBookingSteps {

    private Map<String, Object> request;
    private Response response;
    private Response fetched;
    private String createdId;

    private Response post(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @Given("a unique boarding reservation request")
    public void aUniqueBoardingReservationRequest() {
        request = ApiSupport.uniqueReservationBody(1);
    }

    @Given("a unique boarding reservation request with promo code {string}")
    public void aUniqueBoardingReservationRequestWithPromoCode(String promoCode) {
        request = ApiSupport.uniqueReservationBody(1);
        request.put("promoCode", promoCode);
    }

    @Given("the boarding reservation field {string} is set to {string}")
    public void theBoardingReservationFieldIsSetTo(String field, String value) {
        request.put(field, ApiSupport.typedValue(value));
    }

    @Given("a boarding reservation already exists for a unique room and date")
    public void aBoardingReservationAlreadyExists() {
        request = ApiSupport.uniqueReservationBody(1);
        Response first = post(request);
        assertThat(first.statusCode()).as("initial reservation creation: " + first.asString()).isIn(200, 201);
    }

    @When("another boarding reservation is submitted for the same room and date")
    public void anotherBoardingReservationIsSubmitted() {
        Map<String, Object> second = ApiSupport.reservationBody(ApiSupport.petName(), ApiSupport.email(),
                (Integer) request.get("roomNumber"), (String) request.get("checkInDate"), 1);
        response = post(second);
    }

    @When("the boarding reservation request is submitted")
    public void theBoardingReservationRequestIsSubmitted() {
        response = post(request);
        createdId = ApiSupport.extractId(response);
    }

    @When("an empty boarding reservation request is submitted")
    public void anEmptyBoardingReservationRequestIsSubmitted() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @When("the created boarding reservation is fetched by id")
    public void theCreatedBoardingReservationIsFetchedById() {
        assertThat(createdId).as("created reservation id").isNotNull();
        fetched = Harness.authed().get("/api/reservations/" + createdId);
    }

    @Then("the boarding reservation is accepted with an id")
    public void theBoardingReservationIsAcceptedWithAnId() {
        assertThat(response.statusCode()).as("create status: " + response.asString()).isIn(200, 201);
        assertThat(createdId).as("created reservation id").isNotNull().isNotBlank();
    }

    @Then("the fetched boarding reservation shows the submitted pet name and owner email")
    public void theFetchedBoardingReservationShowsSubmittedValues() {
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("petName")).isEqualTo(request.get("petName"));
        assertThat(fetched.jsonPath().getString("ownerEmail")).isEqualTo(request.get("ownerEmail"));
    }

    @Then("the boarding reservation submission fails with status {int}")
    public void theBoardingReservationSubmissionFailsWithStatus(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
    }
}
