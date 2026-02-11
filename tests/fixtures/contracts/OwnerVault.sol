// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

contract OwnerVault {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function withdraw(address payable recipient, uint256 amount) external {
        require(msg.sender == owner, "not owner");
        _transfer(recipient, amount);
    }

    function _transfer(address payable recipient, uint256 amount) internal {
        (bool ok, ) = recipient.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
