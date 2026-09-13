export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const token = process.env.GH_PAT;
  if (!token) {
    return res.status(500).json({ error: 'GitHub token not configured' });
  }

  const owner = 'kingmarch520-dev';
  const repo = 'spacefacts-pipeline'; // must match the actual repo name exactly
  const workflow_id = 'generate-and-upload.yml'; // must match your .github/workflows/*.yml filename

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow_id}/dispatches`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `token ${token}`,
        'Accept': 'application/vnd.github.v3+json',
      },
      body: JSON.stringify({ ref: 'main' }),
    });

    if (response.ok) {
      res.status(200).json({ message: 'Pipeline triggered successfully!' });
    } else {
      const errorText = await response.text();
      res.status(response.status).json({ error: errorText });
    }
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
