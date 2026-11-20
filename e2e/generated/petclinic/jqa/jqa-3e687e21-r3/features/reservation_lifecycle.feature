Feature: Reservation lifecycle
  Boarding reservations can be created, read, updated and deleted through the API.

  Scenario: Create a boarding reservation and read it back
    Given a new boarding reservation for a unique pet staying 3 nights
    When the client fetches that boarding reservation by its id
    Then the boarding reservation fetch returns status 200
    And the fetched boarding reservation shows the pet name and owner email that were sent

  Scenario: Creating a boarding reservation returns its generated id
    Given a new boarding reservation for a unique pet staying 2 nights
    Then the boarding reservation creation response contains an id

  Scenario: Create a boarding reservation using the WELCOME10 promo code
    When the client books a boarding reservation for a unique pet with promo code "WELCOME10"
    Then the boarding reservation creation succeeds

  Scenario: Update the number of nights of a boarding reservation
    Given a new boarding reservation for a unique pet staying 2 nights
    When the client updates that boarding reservation to 4 nights
    Then the boarding reservation update returns a success status
    And reading that boarding reservation again shows 4 nights

  Scenario: Delete a boarding reservation
    Given a new boarding reservation for a unique pet staying 2 nights
    When the client deletes that boarding reservation
    Then the boarding reservation deletion returns a success status
    And reading that boarding reservation again returns status 404
