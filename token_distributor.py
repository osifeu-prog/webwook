# token_distributor.py - מערכת חלוקת טוקנים אוטומטית
import os
import logging
from web3 import Web3
from decimal import Decimal

logger = logging.getLogger(__name__)

class TokenDistributor:
    def __init__(self):
        self.bsc_rpc = os.environ.get("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
        self.token_contract = os.environ.get("TOKEN_CONTRACT", "0xACb0A09414CEA1C879c67bB7A877E4e19480f022")
        self.private_key = os.environ.get("DISTRIBUTOR_PRIVATE_KEY")
        
        self.w3 = Web3(Web3.HTTPProvider(self.bsc_rpc))
        if not self.w3.is_connected():
            logger.error("Failed to connect to BSC network")
            return
        
        # ABI בסיסי לטוקן BEP-20
        self.token_abi = [
            {
                "constant": False,
                "inputs": [
                    {"name": "_to", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]
        
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.token_contract),
            abi=self.token_abi
        )
        
        self.account = self.w3.eth.account.from_key(self.private_key)
        logger.info(f"Token distributor initialized for {self.account.address}")

    def get_token_balance(self, address: str = None) -> Decimal:
        """מחזיר יתרת טוקנים"""
        try:
            if address is None:
                address = self.account.address
                
            balance = self.contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call()
            
            decimals = self.contract.functions.decimals().call()
            return Decimal(balance) / (10 ** decimals)
        except Exception as e:
            logger.error(f"Failed to get token balance: {e}")
            return Decimal(0)

    def send_tokens(self, to_address: str, amount: Decimal) -> str:
        """שולח טוקנים ומוחזר tx_hash"""
        try:
            decimals = self.contract.functions.decimals().call()
            raw_amount = int(amount * (10 ** decimals))
            
            # בונה טרנזקציה
            transaction = self.contract.functions.transfer(
                Web3.to_checksum_address(to_address),
                raw_amount
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'gas': 100000,
                'gasPrice': self.w3.to_wei('5', 'gwei')
            })
            
            # חותם ושולח
            signed_txn = self.w3.eth.account.sign_transaction(transaction, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            logger.info(f"Sent {amount} tokens to {to_address}, tx: {tx_hash.hex()}")
            return tx_hash.hex()
            
        except Exception as e:
            logger.error(f"Failed to send tokens: {e}")
            return None

    def calculate_task_reward(self, task_number: int) -> Decimal:
        """מחשב תגמול טוקנים לפי מספר משימה"""
        base_reward = Decimal('10')  # טוקנים בסיסיים
        bonus = Decimal(str(task_number * 2))  # בונוס למשימות מתקדמות
        return base_reward + bonus

# instance גלובלי
token_distributor = TokenDistributor()
