Feature: Boarding reservation lifecycle

  Scenario: Create a boarding reservation and read it back
    Given a new boarding reservation has been created for the lifecycle check
    When the lifecycle client fetches the created reservation
    Then the lifecycle response status is 200
    And the fetched reservation matches the submitted pet name and owner email

  Scenario: Create a boarding reservation with the WELCOME10 promo code
    Given a new boarding reservation with promo code "WELCOME10" has been created for the lifecycle check
    When the lifecycle client fetches the created reservation
    Then the lifecycle response status is 200
    And the fetched reservation has promo code "WELCOME10"

  Scenario: Update a boarding reservation and read the change back
    Given a new boarding reservation has been created for the lifecycle check
    When the lifecycle client updates the reservation with a new pet name and 3 nights
    Then the lifecycle response status is successful
    When the lifecycle client fetches the created reservation
    Then the lifecycle response status is 200
    And the fetched reservation shows the updated pet name and 3 nights

  Scenario: Delete a boarding reservation so that it is no longer found
    Given a new boarding reservation has been created for the lifecycle check
    When the lifecycle client deletes the created reservation
    Then the lifecycle response status is successful
    When the lifecycle client fetches the created reservation
    Then the lifecycle response status is 404

  Scenario: Fetching an unknown reservation id returns not found
    When the lifecycle client fetches a reservation id that was never created
    Then the lifecycle response status is 404

  Scenario: Updating an unknown reservation id is rejected
    When the lifecycle client updates a reservation id that was never created
    Then the lifecycle response status is a client error

  Scenario: Deleting an unknown reservation id is rejected
    When the lifecycle client deletes a reservation id that was never created
    Then the lifecycle response status is a client error
