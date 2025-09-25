#!/usr/bin/env python3
"""
EthPingPong.py

2つのウォレット間で指定額を往復送信するスクリプト（ランダム間隔）。
web3.py を使用。EIP-1559 に対応、ガス推定、nonce 管理あり。
"""

import os
import time
import random
import math
from dotenv import load_dotenv
from web3 import Web3, exceptions
from eth_account import Account

load_dotenv()

RPC_URL = os.getenv("RPC_URL")
PK_A = os.getenv("PRIVATE_KEY_A")
PK_B = os.getenv("PRIVATE_KEY_B")
AMOUNT_ETH = os.getenv("AMOUNT_ETH", "0.01")
MIN_DELAY_SEC = float(os.getenv("MIN_DELAY_SEC", "1"))
MAX_DELAY_SEC = float(os.getenv("MAX_DELAY_SEC", "30"))
WAIT_FOR_CONFIRMATIONS = int(os.getenv("WAIT_FOR_CONFIRMATIONS", "1"))

if not RPC_URL or not PK_A or not PK_B:
    raise SystemExit("RPC_URL, PRIVATE_KEY_A, PRIVATE_KEY_B を .env に設定してください。")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    raise SystemExit("RPC に接続できません。RPC_URL を確認してください。")

acct_a = Account.from_key(PK_A)
acct_b = Account.from_key(PK_B)
print(f"Wallet A: {acct_a.address}")
print(f"Wallet B: {acct_b.address}")
print(f"amount (ETH): {AMOUNT_ETH}, delay range: {MIN_DELAY_SEC}-{MAX_DELAY_SEC} sec")

# 初期 nonce を取得してローカルでインクリメントして管理
def get_initial_nonces():
    na = w3.eth.get_transaction_count(acct_a.address, "pending")
    nb = w3.eth.get_transaction_count(acct_b.address, "pending")
    return {"A": na, "B": nb}

nonces = get_initial_nonces()
print("初期 nonce:", nonces)

def compute_fee_values():
    """
    EIP-1559 をサポートする場合は baseFeePerGas を利用して maxFeePerGas と
    maxPriorityFeePerGas を決定する（シンプルなルール）。
    フォールバックで legacy gasPrice を返す。
    """
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas", None)
    if base_fee is not None:
        # web3.py の推奨 priority fee を使う
        try:
            priority = w3.eth.max_priority_fee
        except Exception:
            # 最低限の値
            priority = w3.to_wei(2, "gwei")
        # maxFee = base * (1 + factor) + priority
        # factor を 1.5 にして余裕をもたせる
        max_fee = int(base_fee * 2.5) + int(priority)
        return {"maxPriorityFeePerGas": int(priority), "maxFeePerGas": int(max_fee)}
    else:
        # legacy network
        gp = w3.eth.gas_price
        return {"gasPrice": gp}

def build_and_send(from_acct, to_addr, nonce_key):
    global nonces
    amount_wei = w3.to_wei(AMOUNT_ETH, "ether")
    tx_base = {
        "to": to_addr,
        "value": amount_wei,
        "nonce": nonces[nonce_key],
        "chainId": w3.eth.chain_id,
    }

    # gas estimate
    try:
        estimated = w3.eth.estimate_gas({**tx_base, "from": from_acct.address})
        # 少し余裕を持たせる（+10%）
        gas_limit = math.floor(estimated * 1.1)
    except Exception as e:
        print("ガス推定に失敗、フォールバック 21000 を使用します。", e)
        gas_limit = 21000

    tx_base["gas"] = gas_limit

    # fee settings
    fee_vals = compute_fee_values()
    tx = {**tx_base, **fee_vals}

    # サイン＆送信
    signed = Account.sign_transaction(tx, from_acct.key)
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] tx submitted: {tx_hash.hex()} from {from_acct.address} -> {to_addr} nonce={nonces[nonce_key]} gas={gas_limit}")
        # ローカル nonce を進める
        nonces[nonce_key] += 1

        # レシート待ち（オプション）
        if WAIT_FOR_CONFIRMATIONS > 0:
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120, poll_latency=2)
                print(f"  確認済み: block {receipt.blockNumber} status {receipt.status}")
            except exceptions.TimeExhausted:
                print("  レシート待ちタイムアウト（続行）")
        return tx_hash.hex()
    except Exception as e:
        # nonce 関連やその他エラーのハンドリング
        errstr = str(e)
        print("送信エラー:", errstr)
        if "nonce" in errstr.lower() or "replacement transaction underpriced" in errstr.lower() or "already known" in errstr.lower():
            # ノンスを最新に合わせる
            try:
                current = w3.eth.get_transaction_count(from_acct.address, "pending")
                print(f"  nonce を最新にリセット: {from_acct.address} -> {current}")
                nonces[nonce_key] = current
            except Exception as ee:
                print("  nonce 再取得に失敗:", ee)
        return None

def random_delay():
    return random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)

def main_loop():
    turn = 0  # 偶数: A->B, 奇数: B->A
    while True:
        if turn % 2 == 0:
            send_from = acct_a
            to = acct_b.address
            nkey = "A"
        else:
            send_from = acct_b
            to = acct_a.address
            nkey = "B"

        try:
            build_and_send(send_from, to, nkey)
        except Exception as e:
            print("送信ルーチンで例外:", e)
        delay = random_delay()
        print(f"次の送信まで {delay:.2f} 秒待機...")
        time.sleep(delay)
        turn += 1

if __name__ == "__main__":
    try:
        print("開始します。Ctrl+C で停止します。")
        main_loop()
    except KeyboardInterrupt:
        print("ユーザによって停止されました。")
    except Exception as e:
        print("致命的エラー:", e)
