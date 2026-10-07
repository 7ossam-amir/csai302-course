// x86-64 SSE2: compare four signed 32-bit bucket keys per instruction.
#include <emmintrin.h>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

using Pair = std::pair<std::size_t, std::size_t>;
struct Bucket {
    std::vector<std::int32_t> keys;
    std::vector<std::size_t> positions;
};

std::vector<Pair> hash_join_simd(const std::vector<std::int32_t>& left,
                               const std::vector<std::int32_t>& right,
                               std::size_t bucket_count = 256) {
    if (bucket_count == 0) throw std::invalid_argument("zero bucket count");
    std::unordered_map<std::size_t, Bucket> table;
    auto hash = [bucket_count](std::int32_t key) {
        return static_cast<std::uint32_t>(key) % bucket_count;
    };
    for (std::size_t i = 0; i < left.size(); ++i) {
        auto& bucket = table[hash(left[i])];
        bucket.keys.push_back(left[i]);
        bucket.positions.push_back(i);
    }
    std::vector<Pair> output;
    for (std::size_t j = 0; j < right.size(); ++j) {
        auto found = table.find(hash(right[j]));
        if (found == table.end()) continue;
        const auto& bucket = found->second;
        const __m128i probe = _mm_set1_epi32(right[j]);
        std::size_t i = 0;
        for (; i + 4 <= bucket.keys.size(); i += 4) {
            // Unaligned loads are safe; the loop never reads beyond the bucket.
            const __m128i keys = _mm_loadu_si128(
                reinterpret_cast<const __m128i*>(bucket.keys.data() + i));
            const __m128i matches = _mm_cmpeq_epi32(keys, probe);
            const int mask = _mm_movemask_ps(_mm_castsi128_ps(matches));
            for (int lane = 0; lane < 4; ++lane)
                if (mask & (1 << lane))
                    output.emplace_back(bucket.positions[i + lane], j);
        }
        // Scalar tail handles bucket lengths that are not multiples of four.
        for (; i < bucket.keys.size(); ++i)
            if (bucket.keys[i] == right[j])
                output.emplace_back(bucket.positions[i], j);
    }
    return output;
}

void verify(const std::vector<std::int32_t>& left,
            const std::vector<std::int32_t>& right) {
    std::vector<Pair> expected;
    for (std::size_t i = 0; i < left.size(); ++i)
        for (std::size_t j = 0; j < right.size(); ++j)
            if (left[i] == right[j]) expected.emplace_back(i, j);
    std::sort(expected.begin(), expected.end());
    for (std::size_t count : {1u, 7u, 256u}) {
        auto actual = hash_join_simd(left, right, count);
        std::sort(actual.begin(), actual.end());
        if (actual != expected) throw std::runtime_error("join mismatch");
    }
}

int main() {
    verify({}, {});
    verify({}, {1});
    verify({1, 1, -1, 255, 1}, {1, -1, 255, 2});
    std::mt19937 generator(302);
    std::uniform_int_distribution<std::int32_t> key(-20, 20);
    for (int trial = 0; trial < 100; ++trial) {
        std::vector<std::int32_t> left(trial), right(103 - trial);
        for (auto& value : left) value = key(generator);
        for (auto& value : right) value = key(generator);
        verify(left, right);
    }
    std::cout << "SSE2 hash join: all oracle checks passed\n";
}
